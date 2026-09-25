"""Database models.

Money is stored as an integer count of 1e-8 USD ("nanos") so that the tiny
per-stream amounts DSPs report (often $0.003 or less) add up exactly with no
floating point drift, on SQLite and Postgres alike.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

MONEY_SCALE = Decimal("100000000")  # 1e8
MONEY_QUANT = Decimal("0.00000001")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Money(TypeDecorator):
    """Decimal in Python, BigInteger (1e-8 units) in the database."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return int((Decimal(value) * MONEY_SCALE).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return (Decimal(int(value)) / MONEY_SCALE).quantize(MONEY_QUANT)


class Role(str, enum.Enum):
    artist = "artist"
    admin = "admin"


class ReleaseStatus(str, enum.Enum):
    draft = "draft"
    in_review = "in_review"      # artist submitted, waiting on admin QC
    approved = "approved"        # passed QC, ready to deliver
    delivered = "delivered"      # sent to at least one store
    rejected = "rejected"        # QC failed, back to artist with notes
    taken_down = "taken_down"


class ReleaseType(str, enum.Enum):
    Single = "Single"
    EP = "EP"
    Album = "Album"


class DeliveryStatus(str, enum.Enum):
    queued = "queued"
    sent = "sent"
    acknowledged = "acknowledged"
    failed = "failed"


class DeliveryKind(str, enum.Enum):
    insert = "insert"
    update = "update"
    takedown = "takedown"


class LedgerKind(str, enum.Enum):
    royalty = "royalty"
    commission = "commission"
    payout = "payout"
    payout_reversal = "payout_reversal"
    adjustment = "adjustment"


class PayoutStatus(str, enum.Enum):
    pending = "pending"
    paid = "paid"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.artist)
    legal_name: Mapped[str | None] = mapped_column(String(200))
    country: Mapped[str | None] = mapped_column(String(2))
    stripe_account_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    payouts_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    artists: Mapped[list[Artist]] = relationship(back_populates="owner")

    @property
    def is_admin(self) -> bool:
        return self.role == Role.admin


class Artist(Base):
    """An artist/band name a user manages. One user can run several."""

    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    spotify_artist_id: Mapped[str | None] = mapped_column(String(64))
    apple_artist_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User] = relationship(back_populates="artists")
    releases: Mapped[list[Release]] = relationship(back_populates="artist")


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(primary_key=True)
    artist_id: Mapped[int] = mapped_column(ForeignKey("artists.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    version: Mapped[str | None] = mapped_column(String(200))  # e.g. "Deluxe Edition"
    release_type: Mapped[ReleaseType] = mapped_column(Enum(ReleaseType), default=ReleaseType.Single)
    upc: Mapped[str | None] = mapped_column(String(14), unique=True)
    label_name: Mapped[str] = mapped_column(String(200))
    genre: Mapped[str] = mapped_column(String(100))
    subgenre: Mapped[str | None] = mapped_column(String(100))
    language: Mapped[str] = mapped_column(String(8), default="en")
    release_date: Mapped[date] = mapped_column(Date)
    original_release_date: Mapped[date | None] = mapped_column(Date)
    p_line_year: Mapped[int] = mapped_column(Integer)
    p_line: Mapped[str] = mapped_column(String(300))
    c_line_year: Mapped[int] = mapped_column(Integer)
    c_line: Mapped[str] = mapped_column(String(300))
    explicit: Mapped[bool] = mapped_column(Boolean, default=False)
    territories: Mapped[str] = mapped_column(String(1000), default="Worldwide")  # "Worldwide" or ISO codes
    artwork_path: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[ReleaseStatus] = mapped_column(Enum(ReleaseStatus), default=ReleaseStatus.draft)
    review_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    artist: Mapped[Artist] = relationship(back_populates="releases")
    tracks: Mapped[list[Track]] = relationship(
        back_populates="release", order_by="Track.track_number", cascade="all, delete-orphan"
    )
    deliveries: Mapped[list[Delivery]] = relationship(back_populates="release")


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (UniqueConstraint("release_id", "track_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    track_number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    version: Mapped[str | None] = mapped_column(String(200))  # e.g. "Remix", "Radio Edit"
    isrc: Mapped[str | None] = mapped_column(String(12), unique=True, index=True)
    iswc: Mapped[str | None] = mapped_column(String(15))
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    explicit: Mapped[bool] = mapped_column(Boolean, default=False)
    audio_path: Mapped[str | None] = mapped_column(String(500))
    audio_codec: Mapped[str | None] = mapped_column(String(10))  # FLAC / WAV
    lyrics: Mapped[str | None] = mapped_column(Text)

    release: Mapped[Release] = relationship(back_populates="tracks")
    contributors: Mapped[list[Contributor]] = relationship(
        back_populates="track", cascade="all, delete-orphan", order_by="Contributor.id"
    )
    splits: Mapped[list[Split]] = relationship(
        back_populates="track", cascade="all, delete-orphan", order_by="Split.id"
    )


class Contributor(Base):
    """Credits shown in stores (DDEX DisplayArtist / Contributor)."""

    __tablename__ = "contributors"

    id: Mapped[int] = mapped_column(primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # MainArtist, FeaturedArtist, Composer, Lyricist, Producer, Remixer ...
    role: Mapped[str] = mapped_column(String(50))

    track: Mapped[Track] = relationship(back_populates="contributors")


class Split(Base):
    """Who gets paid for a track, in percent of the track's net revenue.

    A split can point at an existing user, or just an email (the collaborator
    gets linked automatically when they sign up with that email; until then
    their share accrues on an unclaimed balance).
    """

    __tablename__ = "splits"

    id: Mapped[int] = mapped_column(primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    percent: Mapped[Decimal] = mapped_column(Money)

    track: Mapped[Track] = relationship(back_populates="splits")
    user: Mapped[User | None] = relationship()


class DeliveryTarget(Base):
    """A place releases get sent: a DSP's direct feed, or a white-label backend."""

    __tablename__ = "delivery_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    # Transport: local | sftp | s3 | http
    transport: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    recipient_party_id: Mapped[str] = mapped_column(String(64))   # the DSP's DPID
    recipient_party_name: Mapped[str] = mapped_column(String(200))
    test_mode: Mapped[bool] = mapped_column(Boolean, default=True)  # MessageControlType=TestMessage
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Delivery(Base):
    __tablename__ = "deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("delivery_targets.id"), index=True)
    kind: Mapped[DeliveryKind] = mapped_column(Enum(DeliveryKind))
    batch_id: Mapped[str] = mapped_column(String(40))
    message_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[DeliveryStatus] = mapped_column(Enum(DeliveryStatus), default=DeliveryStatus.queued)
    package_path: Mapped[str | None] = mapped_column(String(500))
    remote_ref: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    release: Mapped[Release] = relationship(back_populates="deliveries")
    target: Mapped[DeliveryTarget] = relationship()


class RoyaltyStatement(Base):
    """One imported sales/streaming report file."""

    __tablename__ = "royalty_statements"
    __table_args__ = (UniqueConstraint("source", "file_sha256"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100))   # "Spotify", "FUGA", ...
    period: Mapped[str] = mapped_column(String(20))    # "2026-08"
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    filename: Mapped[str] = mapped_column(String(300))
    file_sha256: Mapped[str] = mapped_column(String(64))
    gross_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    matched_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal(0))
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    lines: Mapped[list[RoyaltyLine]] = relationship(back_populates="statement", cascade="all, delete-orphan")


class RoyaltyLine(Base):
    __tablename__ = "royalty_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey("royalty_statements.id"), index=True)
    track_id: Mapped[int | None] = mapped_column(ForeignKey("tracks.id"), index=True)
    isrc: Mapped[str | None] = mapped_column(String(12), index=True)
    upc: Mapped[str | None] = mapped_column(String(14))
    store: Mapped[str | None] = mapped_column(String(100))
    territory: Mapped[str | None] = mapped_column(String(10))
    usage_type: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(BigInteger, default=0)
    amount: Mapped[Decimal] = mapped_column(Money)
    allocated: Mapped[bool] = mapped_column(Boolean, default=False)

    statement: Mapped[RoyaltyStatement] = relationship(back_populates="lines")
    track: Mapped[Track | None] = relationship()


class LedgerEntry(Base):
    """Append-only money ledger. A user's balance is the sum of their entries.

    user_id NULL + email set  -> money owed to a collaborator who hasn't signed up yet.
    user_id NULL + email NULL -> platform revenue (commission).
    """

    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    kind: Mapped[LedgerKind] = mapped_column(Enum(LedgerKind))
    royalty_line_id: Mapped[int | None] = mapped_column(ForeignKey("royalty_lines.id"), index=True)
    payout_id: Mapped[int | None] = mapped_column(ForeignKey("payouts.id"), index=True)
    memo: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Payout(Base):
    __tablename__ = "payouts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[PayoutStatus] = mapped_column(Enum(PayoutStatus), default=PayoutStatus.pending)
    stripe_transfer_id: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()
