from django.urls import reverse
from rest_framework.test import APITestCase

from factories import CompetitionFactory, CompetitionParticipantFactory, UserFactory


class PendingParticipantsIndicatorTests(APITestCase):
    """
    Organizers see how many participation requests are waiting for approval or denial,
    in their competition list and on the competition itself. Nobody else does.
    """

    def setUp(self):
        self.creator = UserFactory(username='creator', password='creator')
        self.collaborator = UserFactory(username='collab', password='collab')
        self.other_user = UserFactory(username='other', password='other')
        self.competition = CompetitionFactory(
            logo=None, created_by=self.creator, collaborators=[self.collaborator], published=True,
        )
        # 2 requests waiting for a decision, and one of every other kind that must not be counted
        for _ in range(2):
            CompetitionParticipantFactory(competition=self.competition, status='pending')
        for status in ('approved', 'denied', 'unknown'):
            CompetitionParticipantFactory(competition=self.competition, status=status)
        CompetitionParticipantFactory(
            competition=self.competition, status='pending', user=UserFactory(is_deleted=True),
        )
        # A competition of someone else with a pending request must never leak into our list
        self.unrelated = CompetitionFactory(logo=None, created_by=self.other_user, published=True)
        CompetitionParticipantFactory(competition=self.unrelated, status='pending')

    def organizing_list(self, user):
        self.client.force_authenticate(user=user)
        response = self.client.get(reverse('competition-list'), {'mine': 'true', 'type': 'any'})
        assert response.status_code == 200
        return {competition['id']: competition for competition in response.data['results']}

    def detail(self, user):
        self.client.force_authenticate(user=user)
        response = self.client.get(reverse('competition-detail', kwargs={'pk': self.competition.pk}))
        assert response.status_code == 200
        return response.data

    def test_organizing_list_counts_only_pending_requests_of_active_users(self):
        for user in (self.creator, self.collaborator):
            competitions = self.organizing_list(user)
            assert competitions[self.competition.id]['pending_participants_count'] == 2

    def test_organizing_list_shows_zero_when_nothing_is_pending(self):
        empty = CompetitionFactory(logo=None, created_by=self.creator, published=True)
        assert self.organizing_list(self.creator)[empty.id]['pending_participants_count'] == 0

    def test_organizing_list_does_not_include_competitions_of_others(self):
        competitions = self.organizing_list(self.creator)
        assert self.unrelated.id not in competitions

    def test_other_lists_do_not_expose_the_count(self):
        self.client.force_authenticate(user=self.other_user)
        for params in ({}, {'search': self.competition.title}, {'participating_in': 'true'}):
            response = self.client.get(reverse('competition-list'), params)
            assert response.status_code == 200
            for competition in response.data['results']:
                assert 'pending_participants_count' not in competition

    def test_competition_detail_shows_the_count_to_organizers_only(self):
        assert self.detail(self.creator)['pending_participants_count'] == 2
        assert self.detail(self.collaborator)['pending_participants_count'] == 2
        assert 'pending_participants_count' not in self.detail(self.other_user)

    def test_count_goes_down_when_requests_are_decided(self):
        participant = self.competition.participants.filter(status='pending', user__is_deleted=False).first()
        participant.status = 'approved'
        participant.save()
        assert self.detail(self.creator)['pending_participants_count'] == 1
        assert self.organizing_list(self.creator)[self.competition.id]['pending_participants_count'] == 1
