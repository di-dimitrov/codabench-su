import asyncio
from os.path import basename

from django.core.cache import cache
from django.core.exceptions import ValidationError
from profiles.models import CustomGroup
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from api.mixins import DefaultUserCreateMixin
from api.serializers import leaderboards
from api.serializers.tasks import TaskSerializer
from api.serializers.submission_leaderboard import SubmissionScoreSerializer
from competitions.models import Submission, SubmissionDetails, CompetitionParticipant, Phase
from competitions.views import _group_display_name
from datasets.models import Data
from utils.data import make_url_sassy

from tasks.models import Task
from queues.models import Queue


class SubmissionSerializer(serializers.ModelSerializer):
    scores = serializers.SerializerMethodField(read_only=True)
    filename = serializers.SerializerMethodField(read_only=True)
    owner = serializers.CharField(source='owner.username')
    phase_name = serializers.CharField(source='phase.name')
    on_leaderboard = serializers.BooleanField(read_only=True)
    task = TaskSerializer()
    created_when = serializers.DateTimeField()
    auto_run = serializers.SerializerMethodField(read_only=True)
    can_make_submissions_public = serializers.SerializerMethodField(read_only=True)
    participant_group_name = serializers.SerializerMethodField(read_only=True)
    failure_title = serializers.SerializerMethodField(read_only=True)
    failure_message = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Submission
        fields = (
            'phase_name',
            'name',
            'filename',
            'description',
            'created_when',
            'is_public',
            'is_specific_task_re_run',
            'status',
            'status_details',
            'failure_type',
            'failure_title',
            'failure_message',
            'owner',
            'has_children',
            'parent',
            'children',
            'pk',
            'id',
            'phase',
            'scores',
            'fact_sheet_answers',
            'leaderboard',
            'on_leaderboard',
            'task',
            'auto_run',
            'can_make_submissions_public',
            'is_soft_deleted',
            'participant_group_name',
        )
        read_only_fields = (
            'pk',
            'phase',
            'scores',
            'is_specific_task_re_run',
            'leaderboard',
            'on_leaderboard',
        )

    def get_failure_title(self, instance):
        return instance.failure_summary()[0] if instance.status == Submission.FAILED else None

    def get_failure_message(self, instance):
        return instance.failure_summary()[1] if instance.status == Submission.FAILED else None

    def _viewer_is_organizer(self, instance):
        # A list holds the submissions of few competitions, so remember the answer instead of asking for every row
        user = self.context['request'].user
        cache = self.context.setdefault('_organizer_by_competition', {})
        key = (instance.phase.competition_id, user.pk)
        if key not in cache:
            cache[key] = instance.phase.competition.user_has_admin_permission(user)
        return cache[key]

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        # `status_details` of a failed submission can hold tracebacks, host names or paths, which only organizers get.
        # Everyone else gets the plain explanation (`failure_message`). The Human in the Loop messages are meant for all.
        details = representation.get('status_details')
        if (
            instance.status == Submission.FAILED
            and details
            and 'Human in the Loop' not in details
            and not self._viewer_is_organizer(instance)
        ):
            representation['status_details'] = instance.failure_summary()[1]
        return representation

    def get_filename(self, instance):
        if instance.data and instance.data.data_file:
            return basename(instance.data.data_file.name)
        # NOTE: if submission data is None, it means it is soft deleted
        return "Deleted File"

    def get_scores(self, instance):
        scores = [score for score in instance.scores.all() if not score.column.hidden]
        return SubmissionScoreSerializer(scores, many=True, context=self.context).data

    def get_auto_run(self, instance):
        # returns this submission's competition auto_run_submissions Flag
        return instance.phase.competition.auto_run_submissions

    def get_can_make_submissions_public(self, instance):
        # returns this submission's competition can_participants_make_submissions_public Flag
        return instance.phase.competition.can_participants_make_submissions_public

    def get_participant_group_name(self, instance):
        if not instance.queue_id or not instance.phase_id:
            return None

        competition = instance.phase.competition

        groups = competition.participant_groups.filter(
            queue_id=instance.queue_id
        )

        group = groups.filter(
            user__username=instance.owner.username
        ).first()

        if group:
            return _group_display_name(group.name, competition.pk)

        return None


class SubmissionCreationSerializer(DefaultUserCreateMixin, serializers.ModelSerializer):
    """Used for creation _and_ status updates..."""
    data = serializers.SlugRelatedField(queryset=Data.objects.all(), required=False, allow_null=True, slug_field='key')
    filename = serializers.SerializerMethodField(read_only=True)
    tasks = serializers.PrimaryKeyRelatedField(queryset=Task.objects.all(), required=False, write_only=True, many=True)
    selected_groups = serializers.PrimaryKeyRelatedField(queryset=CustomGroup.objects.all(), required=False, write_only=True, many=True)
    phase = serializers.PrimaryKeyRelatedField(queryset=Phase.objects.all(), required=True)
    queue = serializers.PrimaryKeyRelatedField(queryset=Queue.objects.all(), required=False, allow_null=True)
    selected_groups = serializers.PrimaryKeyRelatedField(queryset=CustomGroup.objects.all(), required=False, write_only=True, many=True)
    created_when = serializers.DateTimeField(format="%Y-%m-%d %H:%M", required=False)
    scores = SubmissionScoreSerializer(many=True, required=False)

    class Meta:
        model = Submission
        user_field = 'owner'
        fields = (
            'id',
            'data',
            'phase',
            'status',
            'status_details',
            'failure_type',
            'filename',
            'description',
            'secret',
            'md5',
            'tasks',
            'selected_groups',
            'fact_sheet_answers',
            'organization',
            'queue',
            'created_when',
            'scores'
        )
        extra_kwargs = {
            'secret': {"write_only": True},
            'description': {"read_only": True},
            # 'status': {"read_only": True},
        }

    def get_filename(self, instance):
        if instance.data and instance.data.data_file:
            return basename(instance.data.data_file.name)
        return None

    def create(self, validated_data):
        tasks = validated_data.pop('tasks', None)
        selected_groups = validated_data.pop('selected_groups', None)
        sub = super().create(validated_data)

        # Save the group(s) selected by the user, usefull for when Auto-Run Submission is unchecked
        if selected_groups is not None:
            sub.selected_groups.set(selected_groups)

        if sub.phase.competition.auto_run_submissions:
            group_ids = [g.id for g in selected_groups] if selected_groups is not None else None
            sub.start(tasks=tasks, group_ids=group_ids)

        return sub

    @staticmethod
    def validate_fact_sheet_answers_for(fact_sheet, answers):
        """
        The answers must be given for exactly the questions of the competition's fact sheet, and every required
        question must be answered. A required checkbox must be ticked (for confirmations such as "I followed the
        rules"), a text answer must not be blank, and a selection must be one of its choices.
        """
        if not fact_sheet:
            return
        if not answers:
            required = [question.get('title') or key for key, question in fact_sheet.items()
                        if question.get('is_required') == 'true']
            if required:
                raise ValidationError(f'Please answer the fact sheet questions: {", ".join(required)}')
            return
        if not isinstance(answers, dict):
            raise ValidationError('The fact sheet answers must be a JSON object')
        if set(answers.keys()) != set(fact_sheet.keys()):
            raise ValidationError("Fact Sheet keys do not match Answer keys")
        for key, value in answers.items():
            question = fact_sheet[key]
            title = question.get('title') or key
            required = question.get('is_required') == 'true'
            if question.get('type') == 'checkbox':
                if not isinstance(value, bool):
                    raise ValidationError(f'{title}: the answer must be true or false')
                if required and not value:
                    raise ValidationError(f'{title}: this box must be ticked')
                continue
            if not isinstance(value, str):
                raise ValidationError(f'{title}: the answer must be text')
            choices = question.get('selection')
            if question.get('type') == 'select' and choices and value not in choices:
                raise ValidationError(f'{title}: "{value}" is not one of the choices ({", ".join(c for c in choices if c)})')
            if required and not value.strip():
                raise ValidationError(f'{title} requires an answer')

    def validate(self, attrs):
        data = super().validate(attrs)

        # Checked on every new submission (answers missing altogether must not skip the required questions) and
        # whenever the answers are changed; status updates from the compute worker do not touch them
        if not self.instance or 'fact_sheet_answers' in attrs:
            phase = data.get('phase') or self.instance.phase
            self.validate_fact_sheet_answers_for(phase.competition.fact_sheet, attrs.get('fact_sheet_answers'))

        if attrs.get('tasks'):
            if not all(_ in attrs['phase'].tasks.all() for _ in attrs['tasks']):
                raise ValidationError("All tasks must be part of the current phase.")

        if attrs.get('selected_groups'):
            competition = data['phase'].competition
            user = self.context['request'].user
            valid_group_ids = set(
                competition.participant_groups.filter(user=user).values_list('id', flat=True)
            )
            submitted_ids = set(g.id for g in attrs['selected_groups'])
            if not submitted_ids.issubset(valid_group_ids):
                raise ValidationError("You can only submit to groups you are a member of.")

        if not self.instance:
            is_in_competition = data["phase"].competition.participants.filter(
                user=self.context["request"].user,
                status=CompetitionParticipant.APPROVED
            ).exists()
            if not is_in_competition:
                raise PermissionDenied("You do not have access to this competition to make a submission")

            if not data["phase"].is_active:
                raise ValidationError("This phase is not currently accepting submissions.")

            can_make_submission, reason_why_not = data["phase"].can_user_make_submissions(self.context["request"].user)
            if not can_make_submission:
                raise ValidationError(reason_why_not)

        return data

    def update(self, submission, validated_data):

        # Cannot change submission if secret key is not valid
        if submission.secret != validated_data.get('secret'):
            raise PermissionDenied("Submission secret invalid")

        # Task of a submission cannot be updated
        if "task" in validated_data:
            raise PermissionDenied("Task of a submission cannot be update")

        # A submission that is not failed has no failure type (it may have failed before and been started again)
        if validated_data.get("status") and validated_data["status"] != Submission.FAILED:
            validated_data["failure_type"] = None

        # Update status if it is there in validated data
        if "status" in validated_data:
            # Received a status update, let the frontend know
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()

            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()

            loop.run_until_complete(channel_layer.group_send(f"submission_listening_{submission.owner.pk}", {
                'type': 'submission.message',
                'text': {
                    "kind": "status_update",
                    "status": validated_data["status"],
                },
                'submission_id': submission.id,
            }))

        if validated_data.get('status') == Submission.RUNNING and self.instance.parent is not None and self.instance.parent.status is not Submission.RUNNING:
            self.instance.parent.status = Submission.RUNNING
            self.instance.parent.save()

        if validated_data.get("status") == Submission.SCORING:
            # Start scoring because we're "SCORING" status now from compute worker
            from competitions.tasks import run_submission
            # task = validated_data.get('task_pk')
            # if not task:
            #     raise ValidationError('Cannot update submission. Task pk was not provided')
            # task = Task.objects.get(id=task)
            run_submission(submission.pk, tasks=[submission.task], is_scoring=True)

        elif validated_data.get("status") == Submission.FINISHED:
            # We finished submission, no longer need to store submission stuff in Redis, free it up!
            cache.delete(f"submission-{submission.pk}-log")

        resp = super().update(submission, validated_data)
        if submission.parent:
            submission.parent.check_child_submission_statuses()
        return resp


class SubmissionDetailSerializer(serializers.ModelSerializer):
    data_file = serializers.SerializerMethodField()

    class Meta:
        model = SubmissionDetails
        fields = (
            'name',
            'data_file',
        )

    def get_data_file(self, instance):
        return make_url_sassy(instance.data_file.name)


class SubmissionFilesSerializer(serializers.ModelSerializer):
    logs = serializers.SerializerMethodField()
    data_file = serializers.SerializerMethodField()
    prediction_result = serializers.SerializerMethodField()
    scoring_result = serializers.SerializerMethodField()
    detailed_result = serializers.SerializerMethodField()
    leaderboards = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = (
            'logs',
            'data_file',
            'prediction_result',
            'detailed_result',
            'scoring_result',
            'leaderboards',
            'fact_sheet_answers',
        )

    def get_logs(self, instance):
        if instance.phase.hide_output and not instance.phase.competition.user_has_admin_permission(self.context['request'].user):
            return []
        return SubmissionDetailSerializer(instance.details.all(), many=True).data

    def get_data_file(self, instance):
        return make_url_sassy(instance.data.data_file.name)

    def get_prediction_result(self, instance):
        if instance.prediction_result.name:
            if (instance.phase.hide_output or instance.phase.hide_prediction_output) and not instance.phase.competition.user_has_admin_permission(self.context['request'].user):
                return None
            return make_url_sassy(instance.prediction_result.name)

    def get_detailed_result(self, instance):
        if instance.detailed_result.name:
            if not instance.phase.competition.enable_detailed_results:
                return None
            return make_url_sassy(instance.detailed_result.name)

    def get_scoring_result(self, instance):
        if instance.scoring_result.name:
            if (instance.phase.hide_output or instance.phase.hide_score_output) and not instance.phase.competition.user_has_admin_permission(self.context['request'].user):
                return None
            return make_url_sassy(instance.scoring_result.name)

    def get_leaderboards(self, instance):
        if instance.phase.hide_output and not instance.phase.competition.user_has_admin_permission(self.context['request'].user):
            return None
        boards = list(set([score.column.leaderboard for score in instance.scores.all().select_related('column__leaderboard')]))
        return [leaderboards.LeaderboardSerializer(lb).data for lb in boards]
