"""Import sales/streaming reports from stores or your delivery backend.

Every store and backend formats its reports differently, but they all carry
the same facts: which recording (ISRC), which store, which country, how many
plays/sales, and how much money. The importer finds those columns by header
name, using the aliases below. If a new report uses a header we don't know,
add it to COLUMN_ALIASES rather than writing a new parser.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..identifiers import normalize_isrc
from ..models import RoyaltyLine, RoyaltyStatement, Track

COLUMN_ALIASES: dict[str, list[str]] = {
    "isrc": ["isrc", "isrc code", "track isrc", "asset isrc"],
    "upc": ["upc", "ean", "icpn", "upc/ean", "product upc", "release upc", "barcode"],
    "store": ["store", "dsp", "service", "platform", "retailer", "shop", "store name", "channel", "partner"],
    "territory": ["territory", "country", "country code", "sale country", "region", "iso country"],
    "usage_type": ["usage type", "sale type", "transaction type", "type", "use type", "product type", "offering"],
    "quantity": ["quantity", "units", "streams", "plays", "qty", "count", "number of units"],
    "amount": [
        "amount", "net revenue", "revenue", "earnings", "earnings (usd)", "net amount", "royalty",
        "royalties", "net", "payable", "total", "amount due", "net royalty", "label share", "income",
    ],
}


class ImportError_(ValueError):
    pass


@dataclass
class ImportResult:
    statement: RoyaltyStatement
    duplicate: bool = False


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower().replace("_", " "))


def detect_columns(headers: list[str]) -> dict[str, str]:
    lookup = {_norm(h): h for h in headers}
    mapping: dict[str, str] = {}
    for field_name, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lookup:
                mapping[field_name] = lookup[alias]
                break
    if "amount" not in mapping:
        raise ImportError_(f"No revenue column found. Headers: {headers}")
    if "isrc" not in mapping and "upc" not in mapping:
        raise ImportError_(f"No ISRC or UPC column found. Headers: {headers}")
    return mapping


def _decimal(value: str, decimal_comma: bool = False) -> Decimal:
    cleaned = (value or "").strip().replace("$", "").replace("\u20ac", "").replace(" ", "")
    if "," in cleaned and "." in cleaned:
        # Whichever separator comes last is the decimal point: 1,234.56 or 1.234,56
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", "." if decimal_comma else "")
    if cleaned.startswith("(") and cleaned.endswith(")"):  # accounting negatives
        cleaned = "-" + cleaned[1:-1]
    try:
        return Decimal(cleaned or "0")
    except InvalidOperation:
        raise ImportError_(f"Not a number: {value!r}") from None


def _int(value: str) -> int:
    try:
        return int(Decimal((value or "0").replace(",", "").strip() or "0"))
    except InvalidOperation:
        return 0


def _sniff_dialect(text: str):
    try:
        return csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        return csv.excel


def import_report(
    session: Session,
    content: bytes,
    *,
    source: str,
    period: str,
    filename: str,
    currency: str = "USD",
    default_store: str | None = None,
) -> ImportResult:
    """Parse a CSV/TSV report into a RoyaltyStatement. Does not allocate money yet."""
    sha = hashlib.sha256(content).hexdigest()
    existing = session.scalar(
        select(RoyaltyStatement).where(RoyaltyStatement.source == source, RoyaltyStatement.file_sha256 == sha)
    )
    if existing:
        return ImportResult(existing, duplicate=True)

    text = content.decode("utf-8-sig", errors="replace")
    dialect = _sniff_dialect(text)
    # Semicolon-separated reports come from European systems that write 1,23 for 1.23
    decimal_comma = dialect.delimiter == ";"
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ImportError_("The file is empty")
    cols = detect_columns(list(reader.fieldnames))

    isrc_index = {t.isrc: t.id for t in session.scalars(select(Track).where(Track.isrc.is_not(None)))}

    statement = RoyaltyStatement(source=source, period=period, currency=currency, filename=filename, file_sha256=sha)
    session.add(statement)
    gross = matched = Decimal(0)
    count = unmatched = 0
    for row in reader:
        amount = _decimal(row.get(cols["amount"], ""), decimal_comma)
        isrc = normalize_isrc(row.get(cols.get("isrc", ""), "") or "") or None
        if amount == 0 and not isrc:
            continue  # blank/total rows
        track_id = isrc_index.get(isrc) if isrc else None
        line = RoyaltyLine(
            statement=statement,
            track_id=track_id,
            isrc=isrc,
            upc=(row.get(cols.get("upc", ""), "") or "").strip() or None,
            store=(row.get(cols.get("store", ""), "") or "").strip() or default_store or source,
            territory=(row.get(cols.get("territory", ""), "") or "").strip()[:10] or None,
            usage_type=(row.get(cols.get("usage_type", ""), "") or "").strip()[:50] or None,
            quantity=_int(row.get(cols.get("quantity", ""), "")),
            amount=amount,
        )
        session.add(line)
        count += 1
        gross += amount
        if track_id:
            matched += amount
        else:
            unmatched += 1
    statement.gross_amount = gross
    statement.matched_amount = matched
    statement.line_count = count
    statement.unmatched_count = unmatched
    session.commit()
    return ImportResult(statement)
