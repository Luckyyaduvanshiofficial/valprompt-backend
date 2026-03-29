"""
URL Configuration for prompt_generator project.
"""

from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse

def api_root(request):
    return JsonResponse({
        "name": "Velprompt API",
        "status": "running",
        "version": "v1",
        "message": "Welcome to Velprompt. Access endpoints at /api/v1/"
    })

urlpatterns = [
    path("", api_root, name="api-root"),
    path("admin/", admin.site.urls),
    path("api/v1/", include("api.urls")),
]
