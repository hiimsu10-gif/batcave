"""UPC (release) and ISRC (track) validation and generation.

You need your own prefixes before issuing codes:
  * UPC: a GS1 company prefix (gs1us.org). Until then, your delivery
    backend can assign UPCs for you.
  * ISRC: a registrant code from your national agency (usisrc.org in the US).
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Release, Track

ISRC_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{2}\d{5}$")


def gtin_check_digit(body: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


def is_valid_upc(code: str) -> bool:
    return code.isdigit() and len(code) in (12, 13) and gtin_check_digit(code[:-1]) == code[-1]


def normalize_isrc(code: str) -> str:
    return code.replace("-", "").replace(" ", "").upper()


def is_valid_isrc(code: str) -> bool:
    return bool(ISRC_RE.match(normalize_isrc(code)))


def next_upc(session: Session) -> str:
    prefix = settings.upc_company_prefix
    if not prefix or not prefix.isdigit() or not 6 <= len(prefix) <= 10:
        raise ValueError("UPC_COMPANY_PREFIX is not configured (6-10 digit GS1 prefix)")
    item_len = 11 - len(prefix)
    existing = session.scalars(select(Release.upc).where(Release.upc.like(f"{prefix}%"))).all()
    used = [int(u[len(prefix):11]) for u in existing if u and len(u) == 12]
    nxt = max(used, default=0) + 1
    if nxt >= 10**item_len:
        raise ValueError("UPC range for this company prefix is exhausted")
    body = f"{prefix}{nxt:0{item_len}d}"
    return body + gtin_check_digit(body)


def next_isrc(session: Session, year: int | None = None) -> str:
    reg = settings.isrc_registrant.upper()
    if len(reg) != 3:
        raise ValueError("ISRC_REGISTRANT is not configured (3 characters)")
    yy = f"{(year or date.today().year) % 100:02d}"
    stem = f"{settings.isrc_country.upper()}{reg}{yy}"
    existing = session.scalars(select(Track.isrc).where(Track.isrc.like(f"{stem}%"))).all()
    nxt = max((int(i[7:]) for i in existing if i), default=0) + 1
    if nxt > 99999:
        raise ValueError("ISRC designation codes exhausted for this year")
    return f"{stem}{nxt:05d}"
