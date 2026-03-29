"""
Simple API Key Authentication for the Prompt Generator API.
"""

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings
import os


class APIKeyAuthentication(BaseAuthentication):
    """
    Authenticate against a static API key configured in the environment.
    Format: Authorization: Token <token>
    """

    def authenticate(self, request):
        require_auth = os.getenv("REQUIRE_AUTH", "True").lower() == "true"
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            if require_auth:
                raise AuthenticationFailed("Missing Authorization header.")
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "token":
            if require_auth:
                raise AuthenticationFailed("Invalid Authorization header format. Expected 'Token <key>'.")
            return None

        token = parts[1]
        expected_token = getattr(settings, "API_AUTH_TOKEN", None)

        if expected_token and token == expected_token:
            # Return a simple mock user for DRF permission classes
            class APIServiceUser:
                is_authenticated = True
                def __str__(self):
                    return "API Service User"

            return (APIServiceUser(), None)

        raise AuthenticationFailed("Invalid API token provided.")
