"""
Cross-competition enrollment for SemEval 2027 Task 9.

The competitions in the group share one participant status per user:

* APPROVED on any competition in the group  -> approved on all the others.
* DENIED on any competition in the group    -> denied on all the others.
  Denial always wins: while a user is denied somewhere in the group, an approval
  (organizer click, auto-approve, whitelisted email, sibling fan-out) is turned
  back into a denial instead of being saved.
* An organizer can still reverse a denial on purpose: changing a DENIED row to
  APPROVED/PENDING lifts the denial on the whole group (to the new status).

Mechanism: pre_save/post_save receivers on CompetitionParticipant. They are
event-driven, so they run the instant a participant row is saved, not on a
schedule. They do NOT fire for QuerySet.update() or bulk_create(); the
`sync_task9_participants` command repairs anything those paths miss.
"""

import logging
import threading
from contextlib import contextmanager

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from competitions.models import Competition, CompetitionParticipant

logger = logging.getLogger(__name__)

APPROVED = CompetitionParticipant.APPROVED
DENIED = CompetitionParticipant.DENIED

# Re-entrancy guard: the cascade writes rows, each of which re-fires these
# signals. This thread-local flag stops the fan-out from recursing.
_local = threading.local()


@contextmanager
def suppress_fanout():
    """Save participant rows without triggering the group logic (used by the fan-out and the sync command)."""
    previous = getattr(_local, "fanning_out", False)
    _local.fanning_out = True
    try:
        yield
    finally:
        _local.fanning_out = previous


def group_ids():
    """Return the set of competition PKs that share enrollment.

    Preferred: pin the PKs explicitly in settings as TASK9_COMPETITION_IDS
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


def existing_group_ids():
    """Like group_ids(), but only the competitions that actually exist (a pinned id may be deleted or not created yet)."""
    return set(Competition.objects.filter(id__in=group_ids()).values_list("id", flat=True))


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


def _denied_elsewhere(user_id, competition_id):
    return CompetitionParticipant.objects.filter(
        user_id=user_id, competition_id__in=group_ids(), status=DENIED,
    ).exclude(competition_id=competition_id).exists()


def _skip(**kwargs):
    return kwargs.get("raw") or getattr(_local, "fanning_out", False)


def _set_status(participant, status):
    participant.status = status
    participant.save(update_fields=["status"])
    logger.info(
        "task9 autoenroll: set %s user=%s competition=%s", status, participant.user_id, participant.competition_id,
    )


@receiver(pre_save, sender=CompetitionParticipant, dispatch_uid="task9_denial_wins")
def keep_denial(sender, instance, **kwargs):
    if _skip(**kwargs) or not _competition_in_group(instance):
        return

    # Remember the stored status so post_save can tell a deliberate reversal of a denial
    # (DENIED -> something else) from an ordinary change.
    instance._task9_old_status = (
        sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
        if instance.pk else None
    )

    if (
        instance.status == APPROVED
        and instance._task9_old_status != DENIED
        and _denied_elsewhere(instance.user_id, instance.competition_id)
    ):
        logger.info(
            "task9 autoenroll: kept user=%s denied on competition=%s (denied elsewhere in the group)",
            instance.user_id, instance.competition_id,
        )
        instance.status = DENIED


@receiver(post_save, sender=CompetitionParticipant, dispatch_uid="task9_fanout")
def fanout_status(sender, instance, **kwargs):
    if _skip(**kwargs) or not _competition_in_group(instance):
        return

    old_status = getattr(instance, "_task9_old_status", None)
    new_status = instance.status
    lifting_denial = old_status == DENIED and new_status != DENIED

    if new_status not in (APPROVED, DENIED) and not lifting_denial:
        return

    user_id = instance.user_id
    src_id = instance.competition_id

    def _do():
        with suppress_fanout():
            for cid in existing_group_ids():
                if cid == src_id:
                    continue
                # The user's own save has already gone through, so a problem with one sibling competition must
                # neither fail that request nor stop the remaining siblings from being updated.
                try:
                    _apply_to_competition(user_id, cid, new_status, lifting_denial)
                except Exception:
                    logger.exception(
                        "task9 autoenroll: could not set %s for user=%s on competition=%s", new_status, user_id, cid,
                    )

    # Defer the fan-out until the triggering row is safely committed, so we
    # never act on a save that gets rolled back.
    transaction.on_commit(_do)


def _apply_to_competition(user_id, competition_id, new_status, lifting_denial):
    """Bring the user's row in one sibling competition in line with a decision made in another."""
    existing = CompetitionParticipant.objects.filter(user_id=user_id, competition_id=competition_id).first()

    if new_status not in (APPROVED, DENIED):
        # Lifting a denial to pending/unknown: only touch rows that are still denied, never create any.
        if existing is not None and existing.status == DENIED:
            _set_status(existing, new_status)
        return

    if existing is None:
        _, was_created = CompetitionParticipant.objects.get_or_create(
            user_id=user_id, competition_id=competition_id, defaults={"status": new_status},
        )
        if was_created:
            logger.info("task9 autoenroll: %s user=%s competition=%s", new_status, user_id, competition_id)
        return
    if existing.status == new_status:
        return
    # An approval never overrides a denial, unless it is the organizer lifting that denial.
    if new_status == APPROVED and existing.status == DENIED and not lifting_denial:
        return
    _set_status(existing, new_status)
