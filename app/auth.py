import base64
import os
import secrets

from fastapi import HTTPException, Request, status


def require_auth(request: Request):
    expected_username = os.getenv("AUTH_USERNAME")
    expected_password = os.getenv("AUTH_PASSWORD")

    if not expected_username or not expected_password:
        return None

    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Basic"},
        )

    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    if not (
        secrets.compare_digest(username, expected_username)
        and secrets.compare_digest(password, expected_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return username
