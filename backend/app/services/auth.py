import threading
from functools import wraps

import firebase_admin
from firebase_admin import auth, credentials, exceptions
from flask import current_app, g, request

_init_lock = threading.Lock()

INVALID_TOKEN_ERRORS = (
    ValueError,
    auth.InvalidIdTokenError,
    auth.RevokedIdTokenError,
    auth.UserDisabledError,
)


def _ensure_firebase_app() -> None:
    with _init_lock:
        if firebase_admin._apps:
            return

        path = current_app.config.get("FIREBASE_CREDENTIALS_PATH")
        firebase_admin.initialize_app(credentials.Certificate(path) if path else None)


def verify_firebase_token(token: str) -> dict:
    """Verify a Firebase ID token and return its decoded claims."""
    _ensure_firebase_app()
    return auth.verify_id_token(token)


def require_auth(view):
    """Require a valid Firebase ID token; exposes the user's uid as g.user_id."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        # Imported here to avoid a cycle: app.errors imports the services package.
        from app.errors import ApiError

        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise ApiError(
                401, "unauthorized", "Missing or malformed Authorization header"
            )

        try:
            claims = verify_firebase_token(token.strip())
        except INVALID_TOKEN_ERRORS:
            raise ApiError(401, "unauthorized", "Invalid or expired token") from None
        except exceptions.FirebaseError:
            current_app.logger.exception("Firebase token verification unavailable")
            raise ApiError(
                503, "auth_unavailable", "Authentication service unavailable"
            ) from None

        user_id = claims.get("uid")
        if not user_id:
            raise ApiError(401, "unauthorized", "Invalid or expired token")

        g.user_id = user_id
        return view(*args, **kwargs)

    return wrapper
