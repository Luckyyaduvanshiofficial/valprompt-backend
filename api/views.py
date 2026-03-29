"""
API Views for the Prompt Generator.

Endpoints:
    POST /api/v1/generate/          — Generate a prompt via the full pipeline
    POST /api/v1/test/              — Test a prompt with variable values
    POST /api/v1/improve/           — Improve an existing prompt
    GET  /api/v1/history/           — List prompt generation history
    DELETE /api/v1/history/<id>/    — Delete a history entry
    POST /api/v1/history/<id>/feedback/ — Submit feedback on a prompt
"""

import logging
import time

from rest_framework import status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.generics import ListAPIView, DestroyAPIView
from rest_framework.throttling import AnonRateThrottle
from rest_framework.permissions import IsAuthenticated, IsAdminUser

from .models import PromptHistory
from .serializers import (
    GeneratePromptRequestSerializer,
    PipelineResponseSerializer,
    TestPromptRequestSerializer,
    TestPromptResponseSerializer,
    ImprovePromptRequestSerializer,
    FeedbackRequestSerializer,
    PromptHistorySerializer,
)
from .pipeline import run_pipeline
from .metaprompt import test_prompt, improve_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom Throttle Classes
# ---------------------------------------------------------------------------

class GenerateBurstThrottle(AnonRateThrottle):
    """Burst rate limit for prompt generation (expensive API calls)."""
    rate = "5/min"


class GenerateSustainedThrottle(AnonRateThrottle):
    """Sustained rate limit for prompt generation."""
    rate = "30/hour"


class StandardThrottle(AnonRateThrottle):
    """Standard rate limit for non-generation endpoints."""
    rate = "30/min"


# ---------------------------------------------------------------------------
# Generate Prompt (Full Pipeline)
# ---------------------------------------------------------------------------

@api_view(["POST"])
@throttle_classes([GenerateBurstThrottle, GenerateSustainedThrottle])
def generate_prompt_view(request: Request) -> Response:
    """
    Generate a prompt template via the full multi-stage pipeline.

    Pipeline: Analyze → Classify → Enhance → Select Strategy
              → Generate (Pass 1) → Improve (Pass 2) → Score → Return

    Request body:
        task: str — The task description
        variables: list[str] — Optional variable names

    Response:
        id: int — History record ID
        task: str — The task
        task_type: str — Classified category (blog/coding/agent/general)
        analysis: dict — Structured task analysis
        draft: str — First-pass prompt
        improved: str — Second-pass improved prompt
        final_prompt: str — Best version after auto-improvement
        variables: list[str] — Detected variables
        score: float — Quality score (1-10)
        score_details: dict — Detailed scoring breakdown
        version: int — Number of improvement passes
    """
    serializer = GeneratePromptRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    task = serializer.validated_data["task"]
    variables = serializer.validated_data.get("variables", [])

    try:
        # Run the full pipeline
        start_time = time.time()
        result = run_pipeline(task=task, variables=variables)
        latency_ms = int((time.time() - start_time) * 1000)

        # Save to history with full pipeline data
        history = PromptHistory.objects.create(
            task=task,
            prompt=result["final_prompt"],
            variables=result["variables"],
            raw_response=result.get("raw_response", ""),
            task_type=result["task_type"],
            analysis=result["analysis"],
            draft_prompt=result["draft_prompt"],
            score=result["score"],
            score_details=result.get("score_details", {}),
            version=result["version"],
            latency_ms=latency_ms,
            tokens_used=result.get("tokens", 0),
        )

        response_data = {
            "id": history.id,
            "task": task,
            "task_type": result["task_type"],
            "analysis": result["analysis"],
            "draft": result["draft_prompt"],
            "improved": result["improved_prompt"],
            "final_prompt": result["final_prompt"],
            "variables": result["variables"],
            "score": result["score"],
            "score_details": result.get("score_details", {}),
            "version": result["version"],
            "tokens": result.get("tokens", 0),
            "latency_ms": latency_ms,
        }

        response_serializer = PipelineResponseSerializer(data=response_data)
        response_serializer.is_valid(raise_exception=True)

        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    except RuntimeError as exc:
        logger.error("Pipeline generation failed: %s", exc)
        return Response(
            {"error": str(exc), "code": "GENERATION_FAILED"},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as exc:
        logger.exception("Unexpected error during pipeline generation")
        return Response(
            {"error": "An unexpected error occurred.", "code": "INTERNAL_ERROR"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# Test Prompt
# ---------------------------------------------------------------------------

@api_view(["POST"])
@throttle_classes([StandardThrottle])
def test_prompt_view(request: Request) -> Response:
    """
    Test a prompt template by filling in variable values and running it.

    Request body:
        prompt: str — The prompt template
        variable_values: dict — Variable name -> value mapping

    Response:
        output: str — The AI's response
    """
    serializer = TestPromptRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    prompt_template = serializer.validated_data["prompt"]
    variable_values = serializer.validated_data["variable_values"]

    try:
        output = test_prompt(
            prompt_template=prompt_template,
            variable_values=variable_values,
        )

        return Response(
            {"output": output},
            status=status.HTTP_200_OK,
        )

    except RuntimeError as exc:
        logger.error("Prompt testing failed: %s", exc)
        return Response(
            {"error": str(exc), "code": "TEST_FAILED"},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as exc:
        logger.exception("Unexpected error during prompt testing")
        return Response(
            {"error": "An unexpected error occurred.", "code": "INTERNAL_ERROR"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# Improve Prompt
# ---------------------------------------------------------------------------

@api_view(["POST"])
@throttle_classes([GenerateBurstThrottle, GenerateSustainedThrottle])
def improve_prompt_view(request: Request) -> Response:
    """
    Improve an existing prompt template.

    Request body:
        prompt: str — The existing prompt template
        feedback: str — Optional improvement feedback

    Response:
        id: int — History record ID
        task: str — "Improved prompt"
        prompt: str — The improved prompt
        variables: list[str] — Detected variables
    """
    serializer = ImprovePromptRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    prompt_text = serializer.validated_data["prompt"]
    feedback = serializer.validated_data.get("feedback", "")
    parent_id = request.data.get("parent_id")  # Provide lineage via request explicitly

    try:
        start_time = time.time()
        result = improve_prompt(prompt=prompt_text, feedback=feedback)
        latency_ms = int((time.time() - start_time) * 1000)

        # Save to history
        history = PromptHistory.objects.create(
            task=f"Improved: {prompt_text[:100]}...",
            prompt=result["prompt"],
            variables=result["variables"],
            is_improved=True,
            parent_prompt_id=parent_id,
            latency_ms=latency_ms,
            tokens_used=result.get("tokens", 0),
        )

        return Response(
            {
                "id": history.id,
                "task": history.task,
                "prompt": result["prompt"],
                "variables": result["variables"],
            },
            status=status.HTTP_201_CREATED,
        )

    except RuntimeError as exc:
        logger.error("Prompt improvement failed: %s", exc)
        return Response(
            {"error": str(exc), "code": "IMPROVE_FAILED"},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    except Exception as exc:
        logger.exception("Unexpected error during prompt improvement")
        return Response(
            {"error": "An unexpected error occurred.", "code": "INTERNAL_ERROR"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ---------------------------------------------------------------------------
# User Feedback
# ---------------------------------------------------------------------------

@api_view(["POST"])
@throttle_classes([StandardThrottle])
def feedback_view(request: Request, pk: int) -> Response:
    """
    Submit user feedback (rating + comments) on a generated prompt.

    URL:
        POST /api/v1/history/<id>/feedback/

    Request body:
        rating: int — 1-5 stars
        feedback: str — Optional comments

    Response:
        id: int
        user_rating: int
        user_feedback: str
        message: str
    """
    serializer = FeedbackRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        history = PromptHistory.objects.get(pk=pk)
    except PromptHistory.DoesNotExist:
        return Response(
            {"error": "Prompt history entry not found.", "code": "NOT_FOUND"},
            status=status.HTTP_404_NOT_FOUND,
        )

    history.user_rating = serializer.validated_data["rating"]
    history.user_feedback = serializer.validated_data.get("feedback", "")
    history.save(update_fields=["user_rating", "user_feedback", "updated_at"])

    return Response(
        {
            "id": history.id,
            "user_rating": history.user_rating,
            "user_feedback": history.user_feedback,
            "message": "Feedback recorded successfully.",
        },
        status=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# History Views
# ---------------------------------------------------------------------------

class PromptHistoryListView(ListAPIView):
    """List all generated prompts (paginated)."""

    permission_classes = [IsAuthenticated]
    queryset = PromptHistory.objects.all()
    serializer_class = PromptHistorySerializer


class PromptHistoryDeleteView(DestroyAPIView):
    """Delete a prompt history entry."""

    permission_classes = [IsAuthenticated]
    queryset = PromptHistory.objects.all()
    serializer_class = PromptHistorySerializer
