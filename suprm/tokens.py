"""Signed, expiring links for email verification and password reset."""
from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings
from .models import User

VERIFY_MAX_AGE = 60 * 60 * 24 * 3   # 3 days
RESET_MAX_AGE = 60 * 60             # 1 hour


def _signer(purpose: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt=f"suprm-{purpose}")


def make_verify_token(user: User) -> str:
    return _signer("verify").dumps({"uid": user.id, "email": user.email})


def make_reset_token(user: User) -> str:
    # Tied to the current password hash, so the link dies once the password changes.
    return _signer("reset").dumps({"uid": user.id, "ph": user.password_hash[-16:]})


def read_verify_token(token: str) -> dict | None:
    try:
        return _signer("verify").loads(token, max_age=VERIFY_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def read_reset_token(token: str, user_lookup) -> User | None:
    try:
        data = _signer("reset").loads(token, max_age=RESET_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user = user_lookup(data.get("uid"))
    if not user or user.password_hash[-16:] != data.get("ph"):
        return None
    return user
