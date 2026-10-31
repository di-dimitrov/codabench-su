# api/serializers/submission_leaderboard.py
from rest_framework import serializers
from competitions.models import Submission
from leaderboards.models import SubmissionScore
from api.serializers.profiles import SimpleOrganizationSerializer


class SubmissionScoreSerializer(serializers.ModelSerializer):
    index = serializers.IntegerField(source='column.index', read_only=True)
    column_key = serializers.CharField(source='column.key', read_only=True)
    precision = serializers.IntegerField(source='column.precision', read_only=True)
    is_primary = serializers.SerializerMethodField()

    class Meta:
        model = SubmissionScore
        fields = ('id', 'index', 'score', 'column_key', 'precision', 'is_primary')

    def get_is_primary(self, obj):
        return obj.column.index == obj.column.leaderboard.primary_index


class SubmissionLeaderBoardSerializer(serializers.ModelSerializer):
    scores = SubmissionScoreSerializer(many=True)
    owner = serializers.CharField(source='owner.username')
    display_name = serializers.CharField(source='owner.display_name')
    team_name = serializers.SerializerMethodField()
    slug_url = serializers.CharField(source='owner.slug_url')
    organization = SimpleOrganizationSerializer(allow_null=True)
    created_when = serializers.DateTimeField()
    queue_id = serializers.SerializerMethodField()
    queue_name = serializers.SerializerMethodField()
    fact_sheet_answers = serializers.SerializerMethodField()

    def _fact_sheet_access(self, competition):
        """
        (show every answer?, keys of the questions shown on the leaderboard) for a competition, worked out once.

        Leaderboards are public, so only the answers to "Show On Leaderboard" questions are sent, except to the
        organizers of the competition (their results export needs every answer).
        """
        cache = getattr(self, '_fact_sheet_access_cache', None)
        if cache is None:
            cache = self._fact_sheet_access_cache = {}
        if competition.id not in cache:
            request = self.context.get('request')
            user = getattr(request, 'user', None)
            show_all = bool(user and user.is_authenticated and competition.user_has_admin_permission(user))
            public_keys = {
                key for key, question in (competition.fact_sheet or {}).items()
                if isinstance(question, dict) and question.get('is_on_leaderboard') == 'true'
            }
            cache[competition.id] = (show_all, public_keys)
        return cache[competition.id]

    def get_fact_sheet_answers(self, obj):
        answers = obj.fact_sheet_answers
        if not isinstance(answers, dict) or not answers:
            return answers
        show_all, public_keys = self._fact_sheet_access(obj.phase.competition)
        if show_all:
            return answers
        return {key: value for key, value in answers.items() if key in public_keys}

    def get_team_name(self, obj):
        # Users who signed up before team names existed (or through OIDC) have none
        return (obj.owner.team_name or '').strip() or 'N/A'

    def _get_effective_queue(self, obj):
        if obj.queue:
            return obj.queue

        if obj.parent and obj.parent.queue:
            return obj.parent.queue

        if obj.phase and obj.phase.competition and obj.phase.competition.queue:
            return obj.phase.competition.queue

        return None

    def _get_display_queue_name(self, obj):
        queue = self._get_effective_queue(obj)
        if not queue:
            return None

        raw_name = queue.name or ""
        group_name = raw_name.rsplit("__", 1)[-1]  # comp10__CLB -> CLB, APHP -> APHP
        submission_parent_id = obj.parent_id or obj.id

        return f"{submission_parent_id}_{group_name}"

    def get_queue_name(self, obj):
        return self._get_display_queue_name(obj)

    def get_queue_id(self, obj):
        queue = self._get_effective_queue(obj)
        return queue.id if queue else None

    class Meta:
        model = Submission
        fields = (
            'id', 'parent', 'owner', 'leaderboard_id', 'fact_sheet_answers',
            'task', 'scores', 'display_name', 'team_name', 'slug_url', 'organization',
            'detailed_result', 'created_when', 'queue_name', 'queue_id',
        )
