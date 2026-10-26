"""
Backfill / safety net for the cross-competition signals in autoenroll.signals.

The signals handle new decisions in real time. This command reconciles the
whole group in one pass — useful to (a) fix people decided BEFORE you deployed
the signals, and (b) repair anything the signals missed (QuerySet.update(),
bulk_create(), or an error mid-cascade). It is idempotent: running it
repeatedly never creates duplicates.

Rules (denial wins, since the command cannot know which decision came last):
    * a user DENIED on ANY competition in the group is denied on ALL of them;
    * otherwise a user APPROVED on ANY competition is approved on ALL of them.

Run once by hand:
    docker compose exec django ./manage.py sync_task9_participants

Or on a timer (cron / systemd / Celery Beat) as a safety net. Add --dry-run to
preview without writing.
"""

from django.core.management.base import BaseCommand

from autoenroll.signals import APPROVED, DENIED, existing_group_ids, suppress_fanout
from competitions.models import CompetitionParticipant


class Command(BaseCommand):
    help = (
        "Ensure every user denied on ANY Task 9 competition is denied on ALL of them, and every other user "
        "approved on ANY of them is approved on ALL of them."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change without writing.")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        group = existing_group_ids()
        if not group:
            self.stderr.write(self.style.WARNING(
                "No competitions matched the group. Set TASK9_COMPETITION_IDS "
                "or TASK9_TITLE_PREFIX in settings."))
            return

        in_group = CompetitionParticipant.objects.filter(competition_id__in=group)
        denied_users = set(in_group.filter(status=DENIED).values_list("user_id", flat=True))
        approved_users = set(in_group.filter(status=APPROVED).values_list("user_id", flat=True)) - denied_users

        counts = {DENIED: [0, 0], APPROVED: [0, 0]}  # status -> [created, updated]
        with suppress_fanout():
            for status, users in ((DENIED, denied_users), (APPROVED, approved_users)):
                for uid in users:
                    for cid in group:
                        existing = CompetitionParticipant.objects.filter(user_id=uid, competition_id=cid).first()
                        if existing is None:
                            counts[status][0] += 1
                            if not dry:
                                CompetitionParticipant.objects.create(user_id=uid, competition_id=cid, status=status)
                        elif existing.status != status:
                            counts[status][1] += 1
                            if not dry:
                                existing.status = status
                                existing.save(update_fields=["status"])

        prefix = "[dry-run] would " if dry else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}group={len(group)} competitions, "
            f"denied_users={len(denied_users)} (created={counts[DENIED][0]}, updated={counts[DENIED][1]}), "
            f"approved_users={len(approved_users)} (created={counts[APPROVED][0]}, updated={counts[APPROVED][1]})"
        ))
