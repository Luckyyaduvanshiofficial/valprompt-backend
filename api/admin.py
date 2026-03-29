"""
Admin configuration for the Prompt Generator API.
"""

from django.contrib import admin

from .models import PromptHistory


@admin.register(PromptHistory)
class PromptHistoryAdmin(admin.ModelAdmin):
    """Admin view for PromptHistory with pipeline metadata display."""

    list_display = [
        "id",
        "short_task",
        "task_type",
        "score",
        "version",
        "user_rating",
        "is_improved",
        "created_at",
    ]
    list_filter = ["task_type", "is_improved", "created_at"]
    search_fields = ["task", "prompt"]
    readonly_fields = [
        "task",
        "prompt",
        "variables",
        "raw_response",
        "task_type",
        "analysis",
        "draft_prompt",
        "score",
        "score_details",
        "version",
        "is_improved",
        "user_rating",
        "user_feedback",
        "created_at",
        "updated_at",
    ]
    ordering = ["-created_at"]

    fieldsets = (
        ("Core", {
            "fields": ("task", "prompt", "variables"),
        }),
        ("Pipeline Metadata", {
            "fields": ("task_type", "analysis", "draft_prompt", "score", "score_details", "version"),
            "classes": ("collapse",),
        }),
        ("User Feedback", {
            "fields": ("user_rating", "user_feedback"),
        }),
        ("Debug", {
            "fields": ("raw_response", "is_improved"),
            "classes": ("collapse",),
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at"),
        }),
    )

    @admin.display(description="Task")
    def short_task(self, obj: PromptHistory) -> str:
        """Truncated task for list display."""
        return obj.task[:80] + "..." if len(obj.task) > 80 else obj.task
