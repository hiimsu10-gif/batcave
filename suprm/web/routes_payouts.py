from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Payout, User
from ..payouts.stripe_connect import PaymentError, get_gateway, payable_amount
from .app import render
from .deps import current_user, db, flash, verify_csrf

router = APIRouter()


def gateway():
    """Overridden in tests; raises if Stripe isn't configured."""
    return get_gateway()


@router.get("/payouts")
def payouts_page(request: Request, user: User = Depends(current_user), session: Session = Depends(db)):
    history = session.scalars(select(Payout).where(Payout.user_id == user.id).order_by(Payout.id.desc())).all()
    return render(request, "payouts.html", user=user, history=history, payable=payable_amount(session, user),
                  minimum=settings.min_payout_usd)


@router.post("/payouts/connect", dependencies=[Depends(verify_csrf)])
def connect_stripe(request: Request, user: User = Depends(current_user), session: Session = Depends(db)):
    try:
        gw = gateway()
        if not user.stripe_account_id:
            user.stripe_account_id = gw.create_account(user)
            session.commit()
        url = gw.onboarding_link(
            user.stripe_account_id,
            return_url=f"{settings.base_url}/payouts/return",
            refresh_url=f"{settings.base_url}/payouts",
        )
    except PaymentError as exc:
        flash(request, f"Payouts aren't available yet: {exc}", "error")
        return RedirectResponse("/payouts", status_code=303)
    return RedirectResponse(url, status_code=303)


@router.get("/payouts/return")
def stripe_return(request: Request, user: User = Depends(current_user), session: Session = Depends(db)):
    if user.stripe_account_id:
        try:
            user.payouts_enabled = gateway().payouts_enabled(user.stripe_account_id)
            session.commit()
        except PaymentError:
            pass
    flash(request, "Payout account connected!" if user.payouts_enabled
          else "Stripe still needs a few details before you can be paid.", "success" if user.payouts_enabled
          else "info")
    return RedirectResponse("/payouts", status_code=303)


@router.post("/payouts/dashboard", dependencies=[Depends(verify_csrf)])
def stripe_dashboard(user: User = Depends(current_user)):
    if not user.stripe_account_id:
        raise HTTPException(400, "No payout account yet")
    return RedirectResponse(gateway().dashboard_link(user.stripe_account_id), status_code=303)


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, session: Session = Depends(db)):
    import stripe

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, request.headers.get("stripe-signature"), settings.stripe_webhook_secret
        )
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Bad signature") from None
    if event["type"] == "account.updated":
        account = event["data"]["object"]
        user = session.scalar(select(User).where(User.stripe_account_id == account["id"]))
        if user:
            user.payouts_enabled = bool(account.get("payouts_enabled"))
            session.commit()
    return {"ok": True}
