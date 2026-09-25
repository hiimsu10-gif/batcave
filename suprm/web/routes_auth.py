from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Artist, User
from ..royalties.ledger import claim_pending_balance
from ..security import hash_password, verify_password
from .app import render
from .deps import db, flash, verify_csrf

router = APIRouter()


def _safe_next(url: str | None) -> str:
    return url if url and url.startswith("/") and not url.startswith("//") else "/dashboard"


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
    session: Session = Depends(db),
):
    email = email.strip().lower()
    if len(password) < 10:
        flash(request, "Password must be at least 10 characters", "error")
        return render(request, "signup.html", email=email, artist_name=artist_name)
    if session.scalar(select(User).where(func.lower(User.email) == email)):
        flash(request, "That email already has an account. Log in instead.", "error")
        return RedirectResponse("/login", status_code=303)
    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=artist_name.strip(),
        legal_name=legal_name.strip() or None,
        country=(country or "US").strip().upper()[:2],
    )
    session.add(user)
    session.flush()
    session.add(Artist(owner_id=user.id, name=artist_name.strip()))
    session.commit()
    claim_pending_balance(session, user)  # collaborators invited by email get their splits now
    request.session.clear()
    request.session["uid"] = user.id
    flash(request, "Welcome to Suprm Sounds! Start by creating your first release.", "success")
    return RedirectResponse("/dashboard", status_code=303)


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
    request.session["uid"] = user.id
    return RedirectResponse(_safe_next(next), status_code=303)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
