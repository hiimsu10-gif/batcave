from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import totp
from ..email import EmailError
from ..models import User
from ..security import hash_password, verify_password
from .app import render
from .deps import current_user, db, flash, verify_csrf
from .routes_auth import MIN_PASSWORD, send_verification

router = APIRouter()


@router.get("/account")
def account(request: Request, setup2fa: int = 0, user: User = Depends(current_user),
            session: Session = Depends(db)):
    qr = None
    if not user.totp_enabled and (setup2fa or user.is_admin):
        if not user.totp_secret:
            user.totp_secret = totp.new_secret()
            session.commit()
        qr = totp.qr_svg(totp.provisioning_uri(user.totp_secret, user.email))
        if setup2fa and user.is_admin:
            flash(request, "Admins need two-factor login. Scan the code below to turn it on.", "info")
    return render(request, "account.html", qr=qr)


@router.post("/account/password", dependencies=[Depends(verify_csrf)])
def change_password(request: Request, current: str = Form(...), new: str = Form(...),
                    user: User = Depends(current_user), session: Session = Depends(db)):
    if not verify_password(current, user.password_hash):
        flash(request, "Current password is wrong", "error")
    elif len(new) < MIN_PASSWORD:
        flash(request, f"New password must be at least {MIN_PASSWORD} characters", "error")
    else:
        user.password_hash = hash_password(new)
        session.commit()
        flash(request, "Password changed", "success")
    return RedirectResponse("/account", status_code=303)


@router.post("/account/verify", dependencies=[Depends(verify_csrf)])
def resend_verification(request: Request, user: User = Depends(current_user)):
    try:
        send_verification(user)
        flash(request, f"Sent a new confirmation link to {user.email}", "success")
    except EmailError as exc:
        flash(request, f"Couldn't send email: {exc}", "error")
    return RedirectResponse("/account", status_code=303)


@router.post("/account/2fa/enable", dependencies=[Depends(verify_csrf)])
def enable_2fa(request: Request, code: str = Form(...), user: User = Depends(current_user),
               session: Session = Depends(db)):
    if user.totp_secret and totp.verify(user.totp_secret, code):
        user.totp_enabled = True
        session.commit()
        flash(request, "Two-factor login is on.", "success")
    else:
        flash(request, "That code didn't match. Try the newest code in your app.", "error")
    return RedirectResponse("/account", status_code=303)


@router.post("/account/2fa/disable", dependencies=[Depends(verify_csrf)])
def disable_2fa(request: Request, password: str = Form(...), user: User = Depends(current_user),
                session: Session = Depends(db)):
    if not verify_password(password, user.password_hash):
        flash(request, "Password is wrong", "error")
    else:
        user.totp_enabled, user.totp_secret = False, None
        session.commit()
        flash(request, "Two-factor login is off.", "info")
    return RedirectResponse("/account", status_code=303)
