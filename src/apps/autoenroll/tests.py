from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITransactionTestCase

from autoenroll.signals import suppress_fanout
from competitions.models import CompetitionParticipant
from competitions.tasks import batch_send_email
from factories import CompetitionFactory, UserFactory

APPROVED = CompetitionParticipant.APPROVED
DENIED = CompetitionParticipant.DENIED
PENDING = CompetitionParticipant.PENDING


class Task9GroupTestCase(TestCase):
    """Three competitions share participant status ("group"); a fourth one is outside of it."""

    def setUp(self):
        self.user = UserFactory()
        self.a, self.b, self.c = (CompetitionFactory(logo=None) for _ in range(3))
        self.outside = CompetitionFactory(logo=None)
        group_settings = override_settings(TASK9_COMPETITION_IDS=[self.a.id, self.b.id, self.c.id])
        group_settings.enable()
        self.addCleanup(group_settings.disable)

    def set_status(self, competition, status, user=None):
        """Create or update a participant row the way the API does (Model.save), running on_commit hooks."""
        user = user or self.user
        with self.captureOnCommitCallbacks(execute=True):
            participant = CompetitionParticipant.objects.filter(user=user, competition=competition).first()
            if participant is None:
                participant = CompetitionParticipant(user=user, competition=competition)
            participant.status = status
            participant.save()

    def statuses(self, user=None):
        user = user or self.user
        return dict(CompetitionParticipant.objects.filter(user=user).values_list('competition_id', 'status'))


class SignalTests(Task9GroupTestCase):

    def test_approval_is_shared_with_the_group(self):
        self.set_status(self.a, APPROVED)
        self.assertEqual(self.statuses(), {self.a.id: APPROVED, self.b.id: APPROVED, self.c.id: APPROVED})

    def test_denial_is_shared_with_the_group_and_overrides_other_statuses(self):
        self.set_status(self.b, APPROVED)
        self.set_status(self.c, PENDING)
        self.set_status(self.a, DENIED)
        self.assertEqual(self.statuses(), {self.a.id: DENIED, self.b.id: DENIED, self.c.id: DENIED})

    def test_approval_is_turned_into_denial_when_denied_elsewhere(self):
        self.set_status(self.a, DENIED)
        # e.g. a user the organizers denied joins a sibling competition that auto-approves
        CompetitionParticipant.objects.filter(user=self.user, competition=self.c).delete()
        self.set_status(self.c, APPROVED)
        self.assertEqual(self.statuses()[self.c.id], DENIED)

    def test_pending_row_cannot_be_approved_while_denied_elsewhere(self):
        self.set_status(self.a, DENIED)
        CompetitionParticipant.objects.filter(user=self.user, competition=self.b).update(status=PENDING)
        self.set_status(self.b, APPROVED)
        self.assertEqual(self.statuses(), {self.a.id: DENIED, self.b.id: DENIED, self.c.id: DENIED})

    def test_organizer_can_lift_a_denial_by_approving(self):
        self.set_status(self.a, DENIED)
        self.set_status(self.b, APPROVED)
        self.assertEqual(self.statuses(), {self.a.id: APPROVED, self.b.id: APPROVED, self.c.id: APPROVED})

    def test_lifting_a_denial_to_pending_does_not_create_rows(self):
        self.set_status(self.a, DENIED)
        CompetitionParticipant.objects.filter(user=self.user, competition=self.c).delete()
        self.set_status(self.a, PENDING)
        self.assertEqual(self.statuses(), {self.a.id: PENDING, self.b.id: PENDING})

    def test_pending_and_unknown_are_not_shared(self):
        self.set_status(self.a, PENDING)
        self.assertEqual(self.statuses(), {self.a.id: PENDING})

    def test_competitions_outside_the_group_are_untouched(self):
        self.set_status(self.outside, DENIED)
        self.assertEqual(self.statuses(), {self.outside.id: DENIED})
        self.set_status(self.a, APPROVED)
        self.assertEqual(self.statuses()[self.outside.id], DENIED)

    def test_other_users_are_untouched(self):
        other = UserFactory()
        self.set_status(self.a, DENIED, user=other)
        self.set_status(self.a, APPROVED)
        self.assertEqual(self.statuses(other), {self.a.id: DENIED, self.b.id: DENIED, self.c.id: DENIED})
        self.assertEqual(self.statuses(), {self.a.id: APPROVED, self.b.id: APPROVED, self.c.id: APPROVED})


class SyncCommandTests(Task9GroupTestCase):

    def run_command(self, *args):
        out = StringIO()
        call_command('sync_task9_participants', *args, stdout=out)
        return out.getvalue()

    def make_inconsistent(self):
        """Statuses as they would be if the signals were bypassed (QuerySet.update / bulk_create)"""
        denied_user = UserFactory()
        for competition, status in ((self.a, DENIED), (self.b, APPROVED)):
            CompetitionParticipant.objects.bulk_create(
                [CompetitionParticipant(user=denied_user, competition=competition, status=status)])
        CompetitionParticipant.objects.bulk_create(
            [CompetitionParticipant(user=self.user, competition=self.a, status=APPROVED)])
        return denied_user

    def test_denial_wins_and_approvals_are_shared(self):
        denied_user = self.make_inconsistent()
        self.run_command()
        self.assertEqual(self.statuses(denied_user), {self.a.id: DENIED, self.b.id: DENIED, self.c.id: DENIED})
        self.assertEqual(self.statuses(), {self.a.id: APPROVED, self.b.id: APPROVED, self.c.id: APPROVED})

    def test_dry_run_changes_nothing(self):
        denied_user = self.make_inconsistent()
        before = CompetitionParticipant.objects.count()
        output = self.run_command('--dry-run')
        self.assertIn('[dry-run]', output)
        self.assertEqual(CompetitionParticipant.objects.count(), before)
        self.assertEqual(self.statuses(denied_user), {self.a.id: DENIED, self.b.id: APPROVED})


class ApiFlowTests(APITransactionTestCase):
    """
    The same rules through the real endpoints. APITransactionTestCase commits for real, so on_commit hooks run
    immediately, as they do in production (ATOMIC_REQUESTS is off).
    """

    def setUp(self):
        self.organizer = UserFactory(username='organizer', password='organizer')
        self.user = UserFactory(username='participant', password='participant')
        self.a, self.b, self.c = (
            CompetitionFactory(logo=None, created_by=self.organizer, published=True, registration_auto_approve=True)
            for _ in range(3)
        )
        group_settings = override_settings(TASK9_COMPETITION_IDS=[self.a.id, self.b.id, self.c.id])
        group_settings.enable()
        self.addCleanup(group_settings.disable)

    def statuses(self, user=None):
        user = user or self.user
        return dict(CompetitionParticipant.objects.filter(user=user).values_list('competition_id', 'status'))

    def register(self, competition, username='participant'):
        self.client.login(username=username, password=username)
        return self.client.post(reverse('competition-register', kwargs={'pk': competition.pk}))

    def organizer_sets(self, competition, status, user=None):
        participant = CompetitionParticipant.objects.get(user=user or self.user, competition=competition)
        self.client.login(username='organizer', password='organizer')
        return self.client.patch(reverse('participants-detail', kwargs={'pk': participant.pk}), {'status': status})

    def test_registering_on_an_auto_approve_competition_approves_the_group(self):
        self.assertEqual(self.register(self.a).status_code, 201)
        self.assertEqual(self.statuses(), {self.a.id: 'approved', self.b.id: 'approved', self.c.id: 'approved'})

    def test_organizer_denial_denies_everywhere_and_blocks_registering_again(self):
        self.register(self.a)
        self.assertEqual(self.organizer_sets(self.a, 'denied').status_code, 200)
        self.assertEqual(self.statuses(), {self.a.id: 'denied', self.b.id: 'denied', self.c.id: 'denied'})

        response = self.register(self.b)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.statuses()[self.b.id], 'denied')

    def test_organizer_can_reverse_a_denial(self):
        self.register(self.a)
        self.organizer_sets(self.a, 'denied')
        self.assertEqual(self.organizer_sets(self.b, 'approved').status_code, 200)
        self.assertEqual(self.statuses(), {self.a.id: 'approved', self.b.id: 'approved', self.c.id: 'approved'})

    def test_user_denied_before_the_group_existed_cannot_register_into_approval(self):
        # a denial that was never fanned out (e.g. made before this feature was deployed and not synced yet)
        with suppress_fanout():
            CompetitionParticipant.objects.create(user=self.user, competition=self.a, status='denied')
        self.register(self.b)
        self.assertEqual(self.statuses()[self.b.id], 'denied')

    def test_organizer_messages_skip_denied_participants(self):
        approved_user = UserFactory(username='approved', password='approved')
        self.register(self.a, username='approved')
        self.register(self.a)
        self.organizer_sets(self.a, 'denied')
        self.assertEqual(self.statuses(approved_user)[self.a.id], 'approved')

        with mock.patch('competitions.tasks.codalab_send_markdown_email') as send:
            batch_send_email(self.b.pk, 'hello')
        recipients = send.call_args.kwargs['recipient_list']
        self.assertIn(approved_user.email, recipients)
        self.assertNotIn(self.user.email, recipients)
