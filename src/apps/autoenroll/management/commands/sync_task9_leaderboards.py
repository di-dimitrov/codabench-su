"""
Copy leaderboard settings from one competition of the Task 9 group to all the others.

Set up the leaderboard once, in the competition you use as the master (for example the columns micro_f1 and macro_f1,
micro_f1 as the ranking column), then run:

    docker compose exec django python manage.py sync_task9_leaderboards --from 3

By default it only SHOWS what it would change. Nothing is written until --apply is added:

    docker compose exec django python manage.py sync_task9_leaderboards --from 3 --apply

Leaderboards are matched through the phases: the leaderboard of phase 1 of the master goes to the leaderboard of phase 1
of each other competition, and so on. Columns are matched by their key (micro_f1 with micro_f1). Leaderboards are never
created or deleted; tasks, scoring programs and reference data are not touched.

What can be copied (--fields, comma-separated, replaces the default list; "all" selects everything):

    leaderboard:
      primary_column      the ranking column, copied by its key (the master ranks by micro_f1 -> so do the others)
      submission_rule     which submissions go on the leaderboard (Add, Force_Last, Force_Best, ...)
      hidden              leaderboard hidden from participants
      title               (not in the default) title shown above the leaderboard
      key                 (not in the default) internal key of the leaderboard
    columns:
      columns             create the columns of the master that a leaderboard does not have (with all their settings)
      column_title        title of each column
      column_sorting      descending / ascending
      column_index        position of the column
      column_precision    number of decimals shown
      column_hidden       column hidden from participants
      column_computation  computation and computation_indexes (average, sum, ... over other columns)

Columns a leaderboard has but the master does not are only reported. --delete-extra-columns deletes them, together
with the scores stored in them. Existing submissions get no scores in newly created columns: re-run them if needed.

The group is the one of the auto-enrollment (TASK9_COMPETITION_IDS in the settings).
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from autoenroll.signals import existing_group_ids
from competitions.models import Phase
from leaderboards.models import Column, Leaderboard

LEADERBOARD_FIELDS = ("primary_column", "submission_rule", "hidden", "title", "key")
# option -> the fields of a column it covers
COLUMN_FIELDS = {
    "column_title": ("title",),
    "column_sorting": ("sorting",),
    "column_index": ("index",),
    "column_precision": ("precision",),
    "column_hidden": ("hidden",),
    "column_computation": ("computation", "computation_indexes"),
}
ALLOWED_FIELDS = LEADERBOARD_FIELDS + ("columns",) + tuple(COLUMN_FIELDS)
DEFAULT_FIELDS = tuple(field for field in ALLOWED_FIELDS if field not in ("title", "key"))
# A column that is created gets every setting of the master's column
CREATED_COLUMN_FIELDS = ("title", "sorting", "index", "precision", "hidden", "computation", "computation_indexes")
# Simple fields of a leaderboard, copied as they are (primary_column is handled separately, by column key)
PLAIN_LEADERBOARD_FIELDS = ("submission_rule", "hidden", "title", "key")


class Command(BaseCommand):
    help = (
        "Copy the leaderboard settings (columns, ranking column, submission rule, ...) of one Task 9 competition "
        "(the master) to the other competitions of the group. Shows what would change; nothing is written without "
        "--apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="source", type=int, required=True,
                            help="ID of the competition whose leaderboard settings are copied (the master).")
        parser.add_argument("--fields", default=",".join(DEFAULT_FIELDS),
                            help=f"Comma-separated settings to copy, or 'all'. Default: {','.join(DEFAULT_FIELDS)}. "
                                 f"Also possible: title,key.")
        parser.add_argument("--delete-extra-columns", action="store_true",
                            help="Delete the columns (and their scores) that the master's leaderboard does not have.")
        parser.add_argument("--apply", action="store_true",
                            help="Write the changes. Without it the command only shows them.")

    def handle(self, *args, **options):
        if options["fields"].strip().lower() == "all":
            fields = list(ALLOWED_FIELDS)
        else:
            fields = [field.strip() for field in options["fields"].split(",") if field.strip()]
        unknown = [field for field in fields if field not in ALLOWED_FIELDS]
        if not fields or unknown:
            raise CommandError(
                f"Cannot copy {', '.join(unknown) or 'nothing'}. Allowed: {', '.join(ALLOWED_FIELDS)}"
            )
        delete_extra = options["delete_extra_columns"]

        group = existing_group_ids()
        source_id = options["source"]
        if source_id not in group:
            raise CommandError(f"Competition {source_id} is not in the group {sorted(group)}")

        master_by_phase = {
            phase.index: phase.leaderboard
            for phase in Phase.objects.filter(competition_id=source_id).select_related("leaderboard")
        }
        if not any(master_by_phase.values()):
            raise CommandError(f"Competition {source_id} has no leaderboard")

        reports = []  # (competition id, phase indexes, target leaderboard, plan)
        for competition_id in sorted(group - {source_id}):
            target_phases = {
                phase.index: phase
                for phase in Phase.objects.filter(competition_id=competition_id).select_related("leaderboard")
            }
            pairs = {}  # target leaderboard id -> [master leaderboard, target leaderboard, phase indexes]
            for index, master_leaderboard in sorted(master_by_phase.items()):
                if master_leaderboard is None:
                    continue
                phase = target_phases.get(index)
                if phase is None:
                    self.stderr.write(self.style.WARNING(f"Competition {competition_id} has no phase {index}: skipped"))
                    continue
                if phase.leaderboard is None:
                    self.stderr.write(self.style.WARNING(
                        f"Competition {competition_id}: phase {index} has no leaderboard: skipped"))
                    continue
                pair = pairs.get(phase.leaderboard_id)
                if pair is None:
                    pairs[phase.leaderboard_id] = [master_leaderboard, phase.leaderboard, [index]]
                elif pair[0].pk != master_leaderboard.pk:
                    self.stderr.write(self.style.WARNING(
                        f"Competition {competition_id}: phase {index} shares its leaderboard with phase {pair[2][0]}, "
                        f"but in the master these phases have different leaderboards: phase {index} skipped"))
                else:
                    pair[2].append(index)
            for master_leaderboard, target_leaderboard, indexes in pairs.values():
                plan = self.plan(master_leaderboard, target_leaderboard, fields, delete_extra)
                if plan["lines"] or plan["notes"]:
                    reports.append((competition_id, indexes, target_leaderboard, plan))

        self.stdout.write(f"Master: competition {source_id}. Settings: {', '.join(fields)}."
                          + (" Extra columns are DELETED." if delete_extra else ""))
        current_competition = None
        for competition_id, indexes, target, plan in reports:
            if competition_id != current_competition:
                current_competition = competition_id
                self.stdout.write(f"\nCompetition {competition_id}")
            phases = ", ".join(str(index) for index in indexes)
            self.stdout.write(f"  leaderboard '{target.title}' (#{target.pk}, phase {phases})")
            for line in plan["lines"]:
                self.stdout.write(f"    {line}")
            for note in plan["notes"]:
                self.stdout.write(self.style.WARNING(f"    note: {note}"))

        changed = [report for report in reports if report[3]["lines"]]
        summary = (
            f"{sum(len(plan['lines']) for _, _, _, plan in changed)} change(s) in {len(changed)} leaderboard(s) of "
            f"{len({competition_id for competition_id, _, _, _ in changed})} competition(s)"
        )
        if not changed:
            self.stdout.write(self.style.SUCCESS("\nAll leaderboards already match the master. Nothing to do."))
            return
        if not options["apply"]:
            self.stdout.write(self.style.WARNING(
                f"\n{summary}.\nPREVIEW ONLY, nothing was changed. Run again with --apply to write these changes."))
            return

        # All or nothing
        with transaction.atomic():
            for _, _, target, plan in changed:
                for column in plan["column_deletes"]:
                    column.delete()
                for column, values in plan["column_updates"]:
                    Column.objects.filter(pk=column.pk).update(**values)
                for master_column in plan["column_creates"]:
                    Column.objects.create(
                        leaderboard=target,
                        key=master_column.key,
                        **{field: getattr(master_column, field) for field in CREATED_COLUMN_FIELDS},
                    )
                if plan["leaderboard_updates"]:
                    Leaderboard.objects.filter(pk=target.pk).update(**plan["leaderboard_updates"])

        self.stdout.write(self.style.SUCCESS(f"\nDone: {summary}."))

    def plan(self, master, target, fields, delete_extra):
        """What has to change on `target` to match `master`, and the lines describing it"""
        plan = {
            "lines": [], "notes": [],
            "leaderboard_updates": {}, "column_updates": [], "column_creates": [], "column_deletes": [],
        }
        master_columns = {column.key: column for column in master.columns.all()}
        target_columns = {column.key: column for column in target.columns.all()}

        for field in PLAIN_LEADERBOARD_FIELDS:
            if field in fields and getattr(target, field) != getattr(master, field):
                plan["leaderboard_updates"][field] = getattr(master, field)
                plan["lines"].append(f"{field}: {getattr(target, field)!r} -> {getattr(master, field)!r}")

        column_fields = [name for option, names in COLUMN_FIELDS.items() if option in fields for name in names]
        # Position of every column once the changes are made, to find the ranking column afterwards
        final_index = {key: column.index for key, column in target_columns.items()}

        for key, master_column in master_columns.items():
            target_column = target_columns.get(key)
            if target_column is None:
                if "columns" in fields:
                    plan["column_creates"].append(master_column)
                    final_index[key] = master_column.index
                    plan["lines"].append(
                        f"column {key}: created (title {master_column.title!r}, position {master_column.index}, "
                        f"{master_column.sorting}, {master_column.precision} decimals"
                        f"{', hidden' if master_column.hidden else ''})"
                    )
                else:
                    plan["notes"].append(f"column {key} is missing (add 'columns' to --fields to create it)")
                continue
            values = {
                name: getattr(master_column, name)
                for name in column_fields
                if getattr(target_column, name) != getattr(master_column, name)
            }
            if values:
                plan["column_updates"].append((target_column, values))
                for name, new in values.items():
                    plan["lines"].append(f"column {key}: {name}: {getattr(target_column, name)!r} -> {new!r}")
                if "index" in values:
                    final_index[key] = values["index"]

        for key, target_column in target_columns.items():
            if key in master_columns:
                continue
            if delete_extra:
                plan["column_deletes"].append(target_column)
                final_index.pop(key)
                plan["lines"].append(f"column {key}: DELETED, together with the scores stored in it")
            else:
                plan["notes"].append(
                    f"column {key} is not in the master: kept (--delete-extra-columns would delete it and its scores)")

        positions = list(final_index.values())
        if len(positions) != len(set(positions)):
            plan["notes"].append("some columns would share the same position; check the order of the columns")

        if "primary_column" in fields:
            master_primary = next(
                (column.key for column in master_columns.values() if column.index == master.primary_index), None)
            current_primary = next(
                (column.key for column in target_columns.values() if column.index == target.primary_index), None)
            if master_primary is None:
                plan["notes"].append("the master's ranking column could not be found, ranking column not copied")
            elif master_primary not in final_index:
                plan["notes"].append(
                    f"no column {master_primary} to rank by (add 'columns' to --fields to create it)")
            elif final_index[master_primary] != target.primary_index or current_primary != master_primary:
                plan["leaderboard_updates"]["primary_index"] = final_index[master_primary]
                plan["lines"].append(f"ranking column: {current_primary or 'none'} -> {master_primary}")

        return plan
