"""
DRF Serializers for the Prompt Generator API.
"""

import re
from rest_framework import serializers

from .models import PromptHistory


# ---------------------------------------------------------------------------
# Request Serializers
# ---------------------------------------------------------------------------

class GeneratePromptRequestSerializer(serializers.Serializer):
    """Validates the request body for prompt generation."""

    task = serializers.CharField(
        required=True,
        max_length=5000,
        help_text="Description of the task to generate a prompt for.",
    )
    variables = serializers.ListField(
        child=serializers.CharField(max_length=50),
        required=False,
        default=list,
        help_text="Optional list of variable names to include (e.g. ['DOCUMENT', 'QUESTION']).",
    )

    def validate_variables(self, value):
        for v in value:
            if not re.match(r'^[A-Za-z0-9_]+$', v):
                raise serializers.ValidationError(f"Invalid variable name: '{v}'. Use alphanumeric and underscores.")
        return [v.upper() for v in value]


class TestPromptRequestSerializer(serializers.Serializer):
    """Validates the request body for testing a prompt."""

    prompt = serializers.CharField(
        required=True,
        help_text="The prompt template with {$VARIABLE} placeholders.",
    )
    variable_values = serializers.DictField(
        child=serializers.CharField(),
        required=True,
        help_text="Mapping of variable names to their values.",
    )


class ImprovePromptRequestSerializer(serializers.Serializer):
    """Validates the request body for prompt improvement."""

    prompt = serializers.CharField(
        required=True,
        help_text="The existing prompt template to improve.",
    )
    feedback = serializers.CharField(
        required=False,
        default="",
        help_text="Optional feedback about what needs improvement.",
    )


class FeedbackRequestSerializer(serializers.Serializer):
    """Validates the request body for user feedback on a prompt."""

    rating = serializers.IntegerField(
        required=True,
        min_value=1,
        max_value=5,
        help_text="User satisfaction rating (1-5 stars).",
    )
    feedback = serializers.CharField(
        required=False,
        default="",
        help_text="Optional free-text feedback.",
    )


# ---------------------------------------------------------------------------
# Response / Model Serializers
# ---------------------------------------------------------------------------

class PromptHistorySerializer(serializers.ModelSerializer):
    """Serializer for PromptHistory model (full detail)."""

    class Meta:
        model = PromptHistory
        fields = [
            "id",
            "task",
            "prompt",
            "variables",
            "task_type",
            "analysis",
            "draft_prompt",
            "score",
            "score_details",
            "version",
            "user_rating",
            "user_feedback",
            "tokens_used",
            "latency_ms",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class PipelineResponseSerializer(serializers.Serializer):
    """Response serializer for the full pipeline output."""

    id = serializers.IntegerField()
    task = serializers.CharField()
    task_type = serializers.ListField(child=serializers.ChoiceField(choices=[c[0] for c in PromptHistory.TASK_TYPE_CHOICES]))
    analysis = serializers.DictField()
    draft = serializers.CharField()
    improved = serializers.CharField()
    final_prompt = serializers.CharField()
    variables = serializers.ListField(child=serializers.CharField())
    score = serializers.FloatField()
    score_details = serializers.DictField()
    version = serializers.IntegerField()
    tokens = serializers.IntegerField(required=False, default=0)
    latency_ms = serializers.IntegerField(required=False, default=0)


class GeneratePromptResponseSerializer(serializers.Serializer):
    """Legacy response serializer for prompt generation (backward compatible)."""

    id = serializers.IntegerField()
    task = serializers.CharField()
    prompt = serializers.CharField()
    variables = serializers.ListField(child=serializers.CharField())


class TestPromptResponseSerializer(serializers.Serializer):
    """Response serializer for prompt testing."""

    output = serializers.CharField()
