"""
Optional backfill / safety net for the auto-enrollment signal.

The signal handles new approvals in real time. This command reconciles the
whole group in one pass — useful to (a) enroll people who were approved BEFORE
you deployed the signal, and (b) repair anything the signal missed (e.g. bulk
edits, or an error mid-cascade). It is idempotent: running it repeatedly never
creates duplicates.

Run once by hand:
    docker compose exec django ./manage.py sync_task9_participants

Or on a timer (cron / systemd / Celery Beat) as a safety net. Add --dry-run to
preview without writing.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from competitions.models import Competition, CompetitionParticipant

APPROVED = getattr(CompetitionParticipant, "APPROVED", "approved")


def group_ids():
    ids = getattr(settings, "TASK9_COMPETITION_IDS", None)
    if ids:
        return set(ids)
    prefix = getattr(settings, "TASK9_TITLE_PREFIX", "SemEval 2027 Task 9")
    return set(
        Competition.objects.filter(title__startswith=prefix).values_list("id", flat=True)
    )


class Command(BaseCommand):
    help = "Ensure every user approved on ANY Task 9 competition is approved on ALL of them."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change without writing.")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        group = group_ids()
        if not group:
            self.stderr.write(self.style.WARNING(
                "No competitions matched the group. Set TASK9_COMPETITION_IDS "
                "or TASK9_TITLE_PREFIX in settings."))
            return

        approved_users = set(
            CompetitionParticipant.objects
            .filter(competition_id__in=group, status=APPROVED)
            .values_list("user_id", flat=True)
        )

        created = updated = 0
        for uid in approved_users:
            for cid in group:
                existing = CompetitionParticipant.objects.filter(
                    user_id=uid, competition_id=cid).first()
                if existing is None:
                    created += 1
                    if not dry:
                        CompetitionParticipant.objects.create(
                            user_id=uid, competition_id=cid, status=APPROVED)
                elif existing.status != APPROVED:
                    updated += 1
                    if not dry:
                        existing.status = APPROVED
                        existing.save(update_fields=["status"])

        prefix = "[dry-run] would " if dry else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}group={len(group)} competitions, approved_users={len(approved_users)}, "
            f"created={created}, updated={updated}"))
