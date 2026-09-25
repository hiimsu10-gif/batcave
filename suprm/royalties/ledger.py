"""Turn imported royalty lines into money owed to each artist.

For each matched line:
    commission = amount x PLATFORM_COMMISSION_PERCENT   -> platform ledger
    net        = amount - commission
    each split = net x split.percent / 100              -> payee ledger

Rounding is done to 1e-8 USD; any leftover from rounding goes to the first
split so every line balances to the exact cent-fraction.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..models import (
    MONEY_QUANT,
    LedgerEntry,
    LedgerKind,
    RoyaltyLine,
    RoyaltyStatement,
    Split,
    Track,
    User,
)


def _q(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_DOWN)


def allocate_statement(session: Session, statement: RoyaltyStatement,
                       commission_percent: Decimal | None = None) -> int:
    """Post ledger entries for every matched, unallocated line. Returns lines allocated."""
    pct = settings.platform_commission_percent if commission_percent is None else commission_percent
    lines = session.scalars(
        select(RoyaltyLine)
        .where(RoyaltyLine.statement_id == statement.id, RoyaltyLine.allocated.is_(False),
               RoyaltyLine.track_id.is_not(None))
        .options(selectinload(RoyaltyLine.track).selectinload(Track.splits))
    ).all()
    done = 0
    for line in lines:
        splits = line.track.splits
        if not splits:
            continue  # stays unallocated until splits exist
        commission = _q(line.amount * pct / 100)
        net = line.amount - commission
        memo = f"{statement.source} {statement.period} {line.store or ''} {line.territory or ''}".strip()
        if commission:
            session.add(LedgerEntry(amount=commission, kind=LedgerKind.commission,
                                    royalty_line_id=line.id, memo=memo))
        shares = [_q(net * s.percent / 100) for s in splits]
        shares[0] += net - sum(shares)
        for split, share in zip(splits, shares):
            if share:
                session.add(LedgerEntry(user_id=split.user_id, email=None if split.user_id else split.email,
                                        amount=share, kind=LedgerKind.royalty,
                                        royalty_line_id=line.id, memo=memo))
        line.allocated = True
        done += 1
    session.commit()
    return done


def rematch_unmatched(session: Session) -> int:
    """Link unmatched lines to tracks by ISRC (e.g. after a catalog import)."""
    index = {t.isrc: t.id for t in session.scalars(select(Track).where(Track.isrc.is_not(None)))}
    fixed = 0
    for line in session.scalars(select(RoyaltyLine).where(RoyaltyLine.track_id.is_(None),
                                                          RoyaltyLine.isrc.is_not(None))):
        if line.isrc in index:
            line.track_id = index[line.isrc]
            fixed += 1
    session.commit()
    return fixed


def claim_pending_balance(session: Session, user: User) -> None:
    """When a collaborator signs up, attach splits and money owed to their email."""
    email = user.email.lower()
    for split in session.scalars(select(Split).where(func.lower(Split.email) == email, Split.user_id.is_(None))):
        split.user_id = user.id
    for entry in session.scalars(
        select(LedgerEntry).where(func.lower(LedgerEntry.email) == email, LedgerEntry.user_id.is_(None))
    ):
        entry.user_id = user.id
        entry.email = None
    session.commit()


def balance(session: Session, user_id: int) -> Decimal:
    total = session.scalar(select(func.sum(LedgerEntry.amount)).where(LedgerEntry.user_id == user_id))
    return total or Decimal("0")


def platform_revenue(session: Session) -> Decimal:
    total = session.scalar(
        select(func.sum(LedgerEntry.amount)).where(LedgerEntry.user_id.is_(None), LedgerEntry.email.is_(None))
    )
    return total or Decimal("0")


def unclaimed_total(session: Session) -> Decimal:
    total = session.scalar(
        select(func.sum(LedgerEntry.amount)).where(LedgerEntry.user_id.is_(None), LedgerEntry.email.is_not(None))
    )
    return total or Decimal("0")


def earnings_breakdown(session: Session, user_id: int, by: str = "store") -> list[tuple[str, Decimal, int]]:
    """Royalty earnings grouped by store, territory, period or track title."""
    column = {
        "store": RoyaltyLine.store,
        "territory": RoyaltyLine.territory,
        "period": RoyaltyStatement.period,
        "track": Track.title,
    }[by]
    rows = session.execute(
        select(column, func.sum(LedgerEntry.amount), func.sum(RoyaltyLine.quantity))
        .select_from(LedgerEntry)
        .join(RoyaltyLine, LedgerEntry.royalty_line_id == RoyaltyLine.id)
        .join(RoyaltyStatement, RoyaltyLine.statement_id == RoyaltyStatement.id)
        .join(Track, RoyaltyLine.track_id == Track.id)
        .where(LedgerEntry.user_id == user_id, LedgerEntry.kind == LedgerKind.royalty)
        .group_by(column)
        .order_by(func.sum(LedgerEntry.amount).desc())
    ).all()
    return [(label or "Unknown", amount or Decimal(0), int(qty or 0)) for label, amount, qty in rows]
