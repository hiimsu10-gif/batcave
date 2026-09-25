"""Artist payouts through Stripe Connect (Express accounts).

How the money moves:
  1. DSP / backend royalties land in your business bank account.
  2. You top up your Stripe platform balance from that account
     (Stripe Dashboard -> Balance -> Add funds, or bank transfer).
  3. `run_payouts` sends each artist a Stripe Transfer for their balance.
     Stripe then pays out to the artist's own bank on their schedule.

Stripe handles artist identity checks (KYC), bank details, and 1099-K/1099-NEC
tax forms for US artists, so you never hold bank or SSN data yourself.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Protocol

from sqlalchemy.orm import Session

from ..config import settings
from ..models import LedgerEntry, LedgerKind, Payout, PayoutStatus, User
from ..royalties.ledger import balance


class PaymentError(RuntimeError):
    pass


class PaymentGateway(Protocol):
    def create_account(self, user: User) -> str: ...
    def onboarding_link(self, account_id: str, return_url: str, refresh_url: str) -> str: ...
    def dashboard_link(self, account_id: str) -> str: ...
    def payouts_enabled(self, account_id: str) -> bool: ...
    def transfer(self, account_id: str, amount_cents: int, currency: str, idempotency_key: str,
                 description: str) -> str: ...


class StripeGateway:
    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise PaymentError("STRIPE_SECRET_KEY is not set")
        import stripe

        self.client = stripe.StripeClient(api_key)

    def create_account(self, user: User) -> str:
        account = self.client.v1.accounts.create(params={
            "type": "express",
            "email": user.email,
            "country": user.country or "US",
            "capabilities": {"transfers": {"requested": True}},
            "metadata": {"suprm_user_id": str(user.id)},
        })
        return account.id

    def onboarding_link(self, account_id: str, return_url: str, refresh_url: str) -> str:
        link = self.client.v1.account_links.create(params={
            "account": account_id, "type": "account_onboarding",
            "return_url": return_url, "refresh_url": refresh_url,
        })
        return link.url

    def dashboard_link(self, account_id: str) -> str:
        return self.client.v1.accounts.login_links.create(account_id).url

    def payouts_enabled(self, account_id: str) -> bool:
        return bool(self.client.v1.accounts.retrieve(account_id).payouts_enabled)

    def transfer(self, account_id: str, amount_cents: int, currency: str, idempotency_key: str,
                 description: str) -> str:
        import stripe

        try:
            tr = self.client.v1.transfers.create(
                params={"amount": amount_cents, "currency": currency.lower(), "destination": account_id,
                        "description": description},
                options={"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as exc:
            raise PaymentError(str(exc)) from exc
        return tr.id


def get_gateway() -> PaymentGateway:
    return StripeGateway(settings.stripe_secret_key)


def payable_amount(session: Session, user: User) -> Decimal:
    """Whole cents the user can be paid right now (fractions stay on the balance)."""
    return balance(session, user.id).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def pay_user(session: Session, gateway: PaymentGateway, user: User,
             minimum: Decimal | None = None) -> Payout | None:
    minimum = settings.min_payout_usd if minimum is None else minimum
    if not user.stripe_account_id or not user.payouts_enabled:
        return None
    amount = payable_amount(session, user)
    if amount <= 0 or amount < minimum:
        return None

    # Debit first, so a crash mid-transfer can never pay the same money twice.
    payout = Payout(user_id=user.id, amount=amount)
    session.add(payout)
    session.flush()
    session.add(LedgerEntry(user_id=user.id, amount=-amount, kind=LedgerKind.payout, payout_id=payout.id,
                            memo=f"Payout #{payout.id}"))
    session.commit()

    try:
        payout.stripe_transfer_id = gateway.transfer(
            user.stripe_account_id, int(amount * 100), payout.currency,
            idempotency_key=f"suprm-payout-{payout.id}",
            description=f"Suprm Sounds royalties, payout #{payout.id}",
        )
        payout.status = PayoutStatus.paid
    except PaymentError as exc:
        payout.status = PayoutStatus.failed
        payout.error = str(exc)
        session.add(LedgerEntry(user_id=user.id, amount=amount, kind=LedgerKind.payout_reversal,
                                payout_id=payout.id, memo=f"Payout #{payout.id} failed, returned to balance"))
    session.commit()
    return payout


def run_payouts(session: Session, gateway: PaymentGateway, minimum: Decimal | None = None) -> list[Payout]:
    from sqlalchemy import select

    users = session.scalars(select(User).where(User.payouts_enabled.is_(True))).all()
    return [p for u in users if (p := pay_user(session, gateway, u, minimum))]
