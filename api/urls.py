"""
URL routing for the Prompt Generator API.
"""

from django.urls import path

from .views import (
    generate_prompt_view,
    test_prompt_view,
    improve_prompt_view,
    feedback_view,
    PromptHistoryListView,
    PromptHistoryDeleteView,
)

app_name = "api"

urlpatterns = [
    path("generate/", generate_prompt_view, name="generate"),
    path("test/", test_prompt_view, name="test"),
    path("improve/", improve_prompt_view, name="improve"),
    path("history/", PromptHistoryListView.as_view(), name="history-list"),
    path("history/<int:pk>/", PromptHistoryDeleteView.as_view(), name="history-delete"),
    path("history/<int:pk>/feedback/", feedback_view, name="history-feedback"),
]
