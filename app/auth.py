import os
import secrets

from fastapi import Request


class AuthRequiredException(Exception):
    pass


def require_auth(request: Request):
    expected_username = os.getenv("AUTH_USERNAME")
    expected_password = os.getenv("AUTH_PASSWORD")

    if not expected_username or not expected_password:
        return None

    if request.session.get("user"):
        return request.session["user"]

    raise AuthRequiredException()


def verify_credentials(username: str, password: str) -> bool:
    expected_username = os.getenv("AUTH_USERNAME")
    expected_password = os.getenv("AUTH_PASSWORD")

    if not expected_username or not expected_password:
        return False

    return secrets.compare_digest(username, expected_username) and secrets.compare_digest(
        password, expected_password
    )
