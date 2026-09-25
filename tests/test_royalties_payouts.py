from decimal import Decimal

from sqlalchemy import func, select

from suprm.models import LedgerEntry, PayoutStatus, Split
from suprm.payouts.stripe_connect import PaymentError, pay_user
from suprm.royalties.importer import import_report
from suprm.royalties.ledger import (
    allocate_statement,
    balance,
    claim_pending_balance,
    earnings_breakdown,
    platform_revenue,
    unclaimed_total,
)

from .factories import make_release, make_user

REPORT = b"""Sale Country;DSP;ISRC;Streams;Net Revenue
US;Spotify;USSU12600001;1000;3,50
GB;Apple Music;US-SU1-26-00002;300;"1,20"
DE;Spotify;XXXXX2600009;50;0.30
"""


def _setup(session):
    user = make_user(session)
    release = make_release(session, user)
    return user, release


def test_import_detects_columns_and_flags_unmatched(session):
    _setup(session)
    report = REPORT
    st = import_report(session, report, source="FUGA", period="2026-08", filename="aug.csv").statement
    assert (st.line_count, st.unmatched_count) == (3, 1)
    assert st.gross_amount == Decimal("5.00")
    assert st.matched_amount == Decimal("4.70")
    # Importing the same file twice is a no-op
    assert import_report(session, report, source="FUGA", period="2026-08", filename="aug.csv").duplicate


def test_allocation_with_splits_commission_and_invites(session):
    user, release = _setup(session)
    track = release.tracks[0]
    track.splits = [Split(user_id=user.id, email=user.email, percent=Decimal("66.67")),
                    Split(email="producer@example.com", percent=Decimal("33.33"))]
    session.commit()
    csv = b"isrc,store,territory,quantity,amount\nUSSU12600001,Spotify,US,100000,333.33\n"
    st = import_report(session, csv, source="Spotify", period="2026-08", filename="s.csv").statement
    assert allocate_statement(session, st, commission_percent=Decimal("10")) == 1
    assert allocate_statement(session, st, commission_percent=Decimal("10")) == 0  # idempotent

    total = session.scalar(select(func.sum(LedgerEntry.amount)))
    assert total == Decimal("333.33")  # every cent accounted for
    assert platform_revenue(session) == Decimal("33.333")
    assert balance(session, user.id) + unclaimed_total(session) == Decimal("299.997")

    # The producer signs up later and inherits their share
    producer = make_user(session, email="Producer@example.com", name="Beatz")
    session.commit()
    claim_pending_balance(session, producer)
    assert unclaimed_total(session) == 0
    assert balance(session, producer.id) > Decimal("99.9")
    assert earnings_breakdown(session, user.id, "store")[0][0] == "Spotify"


class FakeGateway:
    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    def transfer(self, account_id, amount_cents, currency, idempotency_key, description):
        self.calls.append((account_id, amount_cents, idempotency_key))
        if self.fail:
            raise PaymentError("insufficient platform balance")
        return "tr_123"


def _funded_user(session, amount="25.126"):
    user, _ = _setup(session)
    user.stripe_account_id, user.payouts_enabled = "acct_1", True
    session.add(LedgerEntry(user_id=user.id, amount=Decimal(amount), kind="royalty"))
    session.commit()
    return user


def test_payout_pays_whole_cents_and_keeps_fraction(session):
    user = _funded_user(session)
    gw = FakeGateway()
    payout = pay_user(session, gw, user)
    assert payout.status == PayoutStatus.paid and payout.amount == Decimal("25.12")
    assert gw.calls == [("acct_1", 2512, f"suprm-payout-{payout.id}")]
    assert balance(session, user.id) == Decimal("0.006")
    assert pay_user(session, gw, user) is None  # below minimum now


def test_failed_payout_returns_money(session):
    user = _funded_user(session)
    payout = pay_user(session, FakeGateway(fail=True), user)
    assert payout.status == PayoutStatus.failed
    assert balance(session, user.id) == Decimal("25.126")


def test_payout_respects_minimum_and_onboarding(session):
    user = _funded_user(session, "9.99")
    assert pay_user(session, FakeGateway(), user) is None
    user.payouts_enabled = False
    session.add(LedgerEntry(user_id=user.id, amount=Decimal("100"), kind="royalty"))
    session.commit()
    assert pay_user(session, FakeGateway(), user) is None
