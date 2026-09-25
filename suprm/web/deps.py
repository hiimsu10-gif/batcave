from __future__ import annotations

import secrets

from fastapi import Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Release, Track, User


class LoginRequired(Exception):
    pass


class TwoFactorSetupRequired(Exception):
    pass


def db(session: Session = Depends(get_session)) -> Session:
    return session


def current_user(request: Request, session: Session = Depends(db)) -> User:
    uid = request.session.get("uid")
    user = session.get(User, uid) if uid else None
    if not user:
        raise LoginRequired()
    request.state.user = user  # lets templates show the nav without passing user everywhere
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    from ..config import settings

    if not user.is_admin:
        raise HTTPException(403, "Admins only")
    if settings.require_admin_2fa and not user.totp_enabled:
        raise TwoFactorSetupRequired()
    return user


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = request.session["csrf"] = secrets.token_urlsafe(32)
    return token


def verify_csrf(request: Request, csrf: str = Form("")) -> None:
    expected = request.session.get("csrf")
    if not expected or not secrets.compare_digest(csrf, expected):
        raise HTTPException(403, "Form expired, go back and try again")


def flash(request: Request, message: str, kind: str = "info") -> None:
    request.session.setdefault("flash", []).append([kind, message])


def owned_release(release_id: int, user: User, session: Session) -> Release:
    release = session.get(Release, release_id)
    if not release or (release.artist.owner_id != user.id and not user.is_admin):
        raise HTTPException(404, "Release not found")
    return release


def owned_track(track_id: int, user: User, session: Session) -> Track:
    track = session.get(Track, track_id)
    if not track:
        raise HTTPException(404, "Track not found")
    owned_release(track.release_id, user, session)
    return track
