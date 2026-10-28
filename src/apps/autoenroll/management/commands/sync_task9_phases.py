"""
Copy phase settings from one competition of the Task 9 group to all the others.

The competitions of the group have the same phases, so a date or a limit that changes has to be changed in every one of
them. Change it once, in the competition you use as the master, then run this command:

    docker compose exec django python manage.py sync_task9_phases --from 3

By default it only SHOWS what it would change (every old and new value). Nothing is written until --apply is added:

    docker compose exec django python manage.py sync_task9_phases --from 3 --apply

Phases are matched by their number (index): phase 0 of the master goes to phase 0 of the others, and so on. Phases are
never created or deleted, and a competition that lacks a phase of the master is reported and skipped.

Only these fields can be copied. Names, descriptions, tasks, leaderboards and files are deliberately not on the list,
they differ between the competitions.

    default:  start, end, execution_time_limit, has_max_submissions, max_submissions_per_day, max_submissions_per_person
    optional: is_final_phase, auto_migrate_to_this_phase, hide_output, hide_prediction_output, hide_score_output,
              public_data, starting_kit
              (pick them with --fields, which replaces the default list, for example
               --fields start,end,starting_kit; or --fields all for every field on this list)

`has_been_migrated` is not on the list: it records what the system did to that phase, it is not a setting.
public_data and starting_kit point to a dataset record; copying them makes the other phases use the very same file,
so only do it when the competitions share them (a starting kit per language, for example, should not be copied).

The group is the one of the auto-enrollment (TASK9_COMPETITION_IDS in the settings).
"""

from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from autoenroll.signals import existing_group_ids
from competitions.models import Competition, Phase
from datasets.models import Data

DEFAULT_FIELDS = (
    "start",
    "end",
    "execution_time_limit",
    "has_max_submissions",
    "max_submissions_per_day",
    "max_submissions_per_person",
)
OPTIONAL_FIELDS = (
    "is_final_phase",
    "auto_migrate_to_this_phase",
    "hide_output",
    "hide_prediction_output",
    "hide_score_output",
    "public_data",
    "starting_kit",
)
ALLOWED_FIELDS = DEFAULT_FIELDS + OPTIONAL_FIELDS

# Fields that point to a dataset record; they are compared and written by the id of that record
FILE_FIELDS = ("public_data", "starting_kit")


def attribute(field):
    return f"{field}_id" if field in FILE_FIELDS else field


def show(value, file_names=None):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if file_names is not None:
        # an id of a dataset record: show its name too
        return "none" if value is None else f"#{value} ({file_names.get(value, 'unknown file')})"
    return str(value)


class Command(BaseCommand):
    help = (
        "Copy the dates and limits of the phases of one Task 9 competition (the master) to the other competitions "
        "of the group. Shows what would change; nothing is written without --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="source", type=int, required=True,
                            help="ID of the competition whose phase settings are copied (the master).")
        parser.add_argument("--fields", default=",".join(DEFAULT_FIELDS),
                            help=f"Comma-separated fields to copy, or 'all'. Default: {','.join(DEFAULT_FIELDS)}. "
                                 f"Also possible: {','.join(OPTIONAL_FIELDS)}.")
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
                f"Cannot copy {', '.join(unknown) or 'no fields'}. Allowed fields: {', '.join(ALLOWED_FIELDS)}"
            )

        group = existing_group_ids()
        source_id = options["source"]
        if source_id not in group:
            raise CommandError(f"Competition {source_id} is not in the group {sorted(group)}")

        source_phases = list(Phase.objects.filter(competition_id=source_id).order_by("index"))
        if not source_phases:
            raise CommandError(f"Competition {source_id} has no phases")

        changes = []  # (competition id, phase, {field: (old value, new value)})
        for competition_id in sorted(group - {source_id}):
            target_phases = {phase.index: phase for phase in Phase.objects.filter(competition_id=competition_id)}
            for source_phase in source_phases:
                target = target_phases.pop(source_phase.index, None)
                if target is None:
                    self.stderr.write(self.style.WARNING(
                        f"Competition {competition_id} has no phase {source_phase.index}: skipped"))
                    continue
                differences = {
                    field: (getattr(target, attribute(field)), getattr(source_phase, attribute(field)))
                    for field in fields
                    if getattr(target, attribute(field)) != getattr(source_phase, attribute(field))
                }
                if differences:
                    changes.append((competition_id, target, differences))
            for index in sorted(target_phases):
                self.stderr.write(self.style.WARNING(
                    f"Competition {competition_id} has a phase {index} that the master does not have: left alone"))

        # Names of the files, so the preview says more than an id
        file_ids = {value for _, _, differences in changes for field, pair in differences.items()
                    if field in FILE_FIELDS for value in pair if value is not None}
        file_names = {data.pk: data.name for data in Data.objects.filter(pk__in=file_ids)}

        self.stdout.write(f"Master: competition {source_id}. Fields: {', '.join(fields)}.")
        current_competition = None
        for competition_id, phase, differences in changes:
            if competition_id != current_competition:
                current_competition = competition_id
                self.stdout.write(f"\nCompetition {competition_id}")
            self.stdout.write(f"  phase {phase.index} ({phase.name})")
            for field, (old, new) in differences.items():
                names = file_names if field in FILE_FIELDS else None
                self.stdout.write(f"    {field}: {show(old, names)}  ->  {show(new, names)}")

        competitions_changed = {competition_id for competition_id, _, _ in changes}
        summary = (
            f"{sum(len(differences) for _, _, differences in changes)} value(s) in {len(changes)} phase(s) of "
            f"{len(competitions_changed)} competition(s) differ from the master"
        )
        if not changes:
            self.stdout.write(self.style.SUCCESS("\nAll competitions already match the master. Nothing to do."))
            return
        if not options["apply"]:
            self.stdout.write(self.style.WARNING(
                f"\n{summary}.\nPREVIEW ONLY, nothing was changed. Run again with --apply to write these changes."))
            return

        # All or nothing; update() leaves everything else about the phases alone
        with transaction.atomic():
            for _, phase, differences in changes:
                Phase.objects.filter(pk=phase.pk).update(
                    **{attribute(field): new for field, (_, new) in differences.items()}
                )

        # Dates moved, so decide again which phase is current, instead of waiting for the hourly job
        for competition in Competition.objects.filter(pk__in=competitions_changed):
            competition.update_phase_statuses()

        self.stdout.write(self.style.SUCCESS(f"\nDone: {summary}. Phase statuses were refreshed."))
