from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import totp
from ..config import settings
from ..email import EmailError, send_email
from ..models import Artist, User
from ..royalties.ledger import claim_pending_balance
from ..security import hash_password, verify_password
from ..tokens import make_reset_token, make_verify_token, read_reset_token, read_verify_token
from .app import render
from .deps import db, flash, verify_csrf

router = APIRouter()

MIN_PASSWORD = 10


def _safe_next(url: str | None) -> str:
    return url if url and url.startswith("/") and not url.startswith("//") else "/dashboard"


def send_verification(user: User) -> None:
    link = f"{settings.base_url}/verify/{make_verify_token(user)}"
    send_email(user.email, "Confirm your Suprm Sounds email",
               f"Hey {user.display_name},\n\nConfirm your email to start releasing music:\n{link}\n\n"
               "This link works for 3 days. If you didn't sign up, ignore this email.\n\n- Suprm Sounds")


@router.get("/")
def home(request: Request):
    if request.session.get("uid"):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "home.html")


@router.get("/signup")
def signup_form(request: Request):
    return render(request, "signup.html")


@router.post("/signup", dependencies=[Depends(verify_csrf)])
def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    artist_name: str = Form(...),
    legal_name: str = Form(""),
    country: str = Form("US"),
    accept_terms: bool = Form(False),
    session: Session = Depends(db),
):
    email = email.strip().lower()
    again = dict(email=email, artist_name=artist_name, legal_name=legal_name, country=country)
    if not accept_terms:
        flash(request, "Please accept the Terms, Artist Distribution Agreement and Privacy Policy", "error")
        return render(request, "signup.html", **again)
    if len(password) < MIN_PASSWORD:
        flash(request, f"Password must be at least {MIN_PASSWORD} characters", "error")
        return render(request, "signup.html", **again)
    if session.scalar(select(User).where(func.lower(User.email) == email)):
        flash(request, "That email already has an account. Log in instead.", "error")
        return RedirectResponse("/login", status_code=303)
    now = datetime.now(timezone.utc)
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=artist_name.strip(),
        legal_name=legal_name.strip() or None,
        country=(country or "US").strip().upper()[:2],
        terms_accepted_at=now,
        terms_version=settings.legal_version,
    )
    session.add(user)
    session.flush()
    session.add(Artist(owner_id=user.id, name=artist_name.strip()))
    session.commit()
    claim_pending_balance(session, user)  # collaborators invited by email get their splits now
    try:
        send_verification(user)
    except EmailError:
        pass  # they can resend from their account page
    request.session.clear()
    request.session["uid"] = user.id
    flash(request, "Welcome to Suprm Sounds! Check your inbox to confirm your email.", "success")
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/verify/{token}")
def verify_email(token: str, request: Request, session: Session = Depends(db)):
    data = read_verify_token(token)
    user = session.get(User, data["uid"]) if data else None
    if not user or user.email != data.get("email"):
        flash(request, "That confirmation link is invalid or expired. Send a new one from your account.", "error")
    else:
        user.email_verified_at = user.email_verified_at or datetime.now(timezone.utc)
        session.commit()
        flash(request, "Email confirmed. You're all set.", "success")
    return RedirectResponse("/dashboard" if request.session.get("uid") else "/login", status_code=303)


@router.get("/login")
def login_form(request: Request, next: str | None = None):
    return render(request, "login.html", next=next)


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    session: Session = Depends(db),
):
    user = session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if not user or not verify_password(password, user.password_hash):
        flash(request, "Wrong email or password", "error")
        return render(request, "login.html", next=next, email=email)
    request.session.clear()
    if user.totp_enabled:
        request.session["pending_uid"] = user.id
        request.session["pending_next"] = _safe_next(next)
        return RedirectResponse("/login/2fa", status_code=303)
    request.session["uid"] = user.id
    return RedirectResponse(_safe_next(next), status_code=303)


@router.get("/login/2fa")
def login_2fa_form(request: Request):
    if not request.session.get("pending_uid"):
        return RedirectResponse("/login", status_code=303)
    return render(request, "login_2fa.html")


@router.post("/login/2fa", dependencies=[Depends(verify_csrf)])
def login_2fa(request: Request, code: str = Form(...), session: Session = Depends(db)):
    user = session.get(User, request.session.get("pending_uid") or 0)
    if not user or not user.totp_secret:
        return RedirectResponse("/login", status_code=303)
    attempts = request.session.get("2fa_attempts", 0) + 1
    if attempts > 5:
        request.session.clear()
        flash(request, "Too many wrong codes. Log in again.", "error")
        return RedirectResponse("/login", status_code=303)
    if not totp.verify(user.totp_secret, code):
        request.session["2fa_attempts"] = attempts
        flash(request, "That code didn't match. Check your authenticator app's clock and try again.", "error")
        return render(request, "login_2fa.html")
    nxt = request.session.get("pending_next", "/dashboard")
    request.session.clear()
    request.session["uid"] = user.id
    return RedirectResponse(nxt, status_code=303)


@router.get("/forgot")
def forgot_form(request: Request):
    return render(request, "forgot.html")


@router.post("/forgot", dependencies=[Depends(verify_csrf)])
def forgot(request: Request, email: str = Form(...), session: Session = Depends(db)):
    user = session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if user:
        link = f"{settings.base_url}/reset/{make_reset_token(user)}"
        try:
            send_email(user.email, "Reset your Suprm Sounds password",
                       f"Someone (hopefully you) asked to reset your password.\n\n{link}\n\n"
                       "This link works for 1 hour. If it wasn't you, ignore this email.\n\n- Suprm Sounds")
        except EmailError:
            pass
    # Same answer either way, so this page can't be used to find out who has an account
    flash(request, "If that email has an account, a reset link is on its way.", "success")
    return RedirectResponse("/login", status_code=303)


@router.get("/reset/{token}")
def reset_form(token: str, request: Request, session: Session = Depends(db)):
    if not read_reset_token(token, lambda uid: session.get(User, uid or 0)):
        flash(request, "That reset link is invalid or expired. Ask for a new one.", "error")
        return RedirectResponse("/forgot", status_code=303)
    return render(request, "reset.html", token=token)


@router.post("/reset/{token}", dependencies=[Depends(verify_csrf)])
def reset(token: str, request: Request, password: str = Form(...), session: Session = Depends(db)):
    user = read_reset_token(token, lambda uid: session.get(User, uid or 0))
    if not user:
        flash(request, "That reset link is invalid or expired. Ask for a new one.", "error")
        return RedirectResponse("/forgot", status_code=303)
    if len(password) < MIN_PASSWORD:
        flash(request, f"Password must be at least {MIN_PASSWORD} characters", "error")
        return render(request, "reset.html", token=token)
    user.password_hash = hash_password(password)
    user.email_verified_at = user.email_verified_at or datetime.now(timezone.utc)  # they proved inbox access
    session.commit()
    request.session.clear()
    flash(request, "Password updated. Log in with your new password.", "success")
    return RedirectResponse("/login", status_code=303)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
