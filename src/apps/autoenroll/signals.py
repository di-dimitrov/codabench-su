"""
Cross-competition auto-enrollment for SemEval 2027 Task 9.

When a participant is APPROVED on ANY competition in the group (OR semantics),
they are automatically approved on all the others.

Mechanism: a post_save receiver on CompetitionParticipant. It is event-driven —
it runs the instant an approval row is saved, not on a schedule.

IMPORTANT — verify against your instance before trusting this (models can differ
between Codabench versions). Run:

    docker compose exec django ./manage.py shell_plus --quiet-load -c \
      "from competitions.models import CompetitionParticipant as C; \
       print(C._meta.app_label, C.__name__); \
       print([f.name for f in C._meta.get_fields()]); \
       print(getattr(C,'STATUS', getattr(C,'STATUSES', 'no STATUS attr')))"

Confirm: the model is competitions.CompetitionParticipant, it has fields
`user`, `competition`, `status`, and the approved value is "approved". If the
import path is "apps.competitions.models", update the import below.
"""

import logging
import threading

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from competitions.models import Competition, CompetitionParticipant

logger = logging.getLogger(__name__)

# Resolve status values robustly (Codabench uses APPROVED = "approved").
APPROVED = getattr(CompetitionParticipant, "APPROVED", "approved")
DENIED = getattr(CompetitionParticipant, "DENIED", "denied")

# If True, a sibling where the organizer EXPLICITLY denied the user is left
# denied rather than flipped to approved. Default False = approve on all 12,
# which matches "accepted for all". Override in settings if you prefer.
RESPECT_DENIALS = getattr(settings, "TASK9_RESPECT_DENIALS", False)

# Re-entrancy guard: the cascade writes approved rows, each of which re-fires
# this signal. This thread-local flag stops the fan-out from recursing.
_local = threading.local()


def _group_ids():
    """Return the set of competition PKs that share enrollment.

    Preferred: pin the 12 PKs explicitly in settings/env as TASK9_COMPETITION_IDS
    (a list of ints). Fallback: match competitions whose title starts with
    TASK9_TITLE_PREFIX (default "SemEval 2027 Task 9").
    """
    ids = getattr(settings, "TASK9_COMPETITION_IDS", None)
    if ids:
        return set(ids)
    prefix = getattr(settings, "TASK9_TITLE_PREFIX", "SemEval 2027 Task 9")
    return set(
        Competition.objects.filter(title__startswith=prefix).values_list("id", flat=True)
    )


def _competition_in_group(instance):
    """Cheap check whether the just-saved row belongs to the group.

    Uses competition_id (no extra query) when explicit IDs are configured;
    otherwise falls back to a title check on the related competition.
    """
    ids = getattr(settings, "TASK9_COMPETITION_IDS", None)
    if ids:
        return instance.competition_id in set(ids)
    prefix = getattr(settings, "TASK9_TITLE_PREFIX", "SemEval 2027 Task 9")
    title = getattr(instance.competition, "title", "") or ""
    return title.startswith(prefix)


@receiver(post_save, sender=CompetitionParticipant, dispatch_uid="task9_fanout_approval")
def fanout_approval(sender, instance, created, **kwargs):
    # 1) Only react to approvals.
    if instance.status != APPROVED:
        return
    # 2) Don't let the cascade re-trigger itself.
    if getattr(_local, "fanning_out", False):
        return
    # 3) Only fan out for competitions in the linked group.
    if not _competition_in_group(instance):
        return

    user_id = instance.user_id
    src_id = instance.competition_id

    def _do():
        _local.fanning_out = True
        try:
            for cid in _group_ids():
                if cid == src_id:
                    continue
                obj, was_created = CompetitionParticipant.objects.get_or_create(
                    user_id=user_id,
                    competition_id=cid,
                    defaults={"status": APPROVED},
                )
                if was_created:
                    logger.info("task9 autoenroll: approved user=%s competition=%s", user_id, cid)
                    continue
                if obj.status == APPROVED:
                    continue
                if RESPECT_DENIALS and obj.status == DENIED:
                    continue
                obj.status = APPROVED
                obj.save(update_fields=["status"])
                logger.info("task9 autoenroll: re-approved user=%s competition=%s", user_id, cid)
        finally:
            _local.fanning_out = False

    # Defer the fan-out until the triggering row is safely committed, so we
    # never act on a save that gets rolled back.
    transaction.on_commit(_do)
