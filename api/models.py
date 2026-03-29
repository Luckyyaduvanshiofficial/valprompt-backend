"""
Models for the Prompt Generator API.
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class PromptHistory(models.Model):
    """Stores generated prompt templates with full pipeline metadata."""

    TASK_TYPE_CHOICES = [
        ("blog", "Blog / Content"),
        ("coding", "Coding / Development"),
        ("agent", "Agent / Automation"),
        ("general", "General"),
    ]

    # --- Core Fields ---
    task = models.TextField(
        help_text="The original task description provided by the user."
    )
    prompt = models.TextField(
        help_text="The final (best) generated prompt template."
    )
    variables = models.JSONField(
        default=list,
        help_text="List of variable names extracted from the prompt.",
    )
    raw_response = models.TextField(
        blank=True,
        default="",
        help_text="Raw metaprompt response (for debugging).",
    )

    # --- Pipeline Fields ---
    task_type = models.JSONField(
        default=list,
        help_text="List of classified task categories (e.g. ['blog', 'coding']).",
    )
    analysis = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured task analysis (goal, audience, tone, format, constraints).",
    )
    draft_prompt = models.TextField(
        blank=True,
        default="",
        help_text="First-pass generated prompt before improvement.",
    )
    score = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(10.0)],
        help_text="Quality score from the evaluation system (1-10).",
    )
    score_details = models.JSONField(
        default=dict,
        blank=True,
        help_text="Detailed scoring breakdown by criteria.",
    )
    version = models.IntegerField(
        default=1,
        help_text="Number of improvement passes applied.",
    )
    parent_prompt_id = models.IntegerField(
        null=True,
        blank=True,
        help_text="Lineage tracking: ID of the prompt this was improved from.",
    )

    # --- Observability Fields ---
    tokens_used = models.IntegerField(
        null=True,
        blank=True,
        help_text="Total LLM tokens consumed during pipeline execution.",
    )
    latency_ms = models.IntegerField(
        null=True,
        blank=True,
        help_text="Total time taken by the pipeline in milliseconds.",
    )

    # --- Improvement & Feedback ---
    is_improved = models.BooleanField(
        default=False,
        help_text="Whether this prompt was improved from an existing one.",
    )
    user_rating = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="User satisfaction rating (1-5 stars).",
    )
    user_feedback = models.TextField(
        blank=True,
        default="",
        help_text="Free-text feedback from the user.",
    )

    # --- Timestamps ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Prompt Histories"

    def __str__(self) -> str:
        score_str = f" (score={self.score:.1f})" if self.score else ""
        return f"[{self.created_at:%Y-%m-%d %H:%M}] [{self.task_type}]{score_str} {self.task[:60]}..."
