from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..config import settings
from ..ddex.package import build_package
from ..identifiers import next_isrc, next_upc
from ..models import (
    Delivery,
    DeliveryKind,
    DeliveryStatus,
    DeliveryTarget,
    Release,
    ReleaseStatus,
)
from ..qc import check_release
from .transports import TransportError, make_transport


class DeliveryError(RuntimeError):
    pass


def assign_codes(session: Session, release: Release) -> None:
    """Give the release a UPC and every track an ISRC if they lack one."""
    if not release.upc:
        release.upc = next_upc(session)
        session.flush()
    for track in release.tracks:
        if not track.isrc:
            track.isrc = next_isrc(session)
            session.flush()


def approve_release(session: Session, release: Release) -> None:
    if release.status not in (ReleaseStatus.in_review, ReleaseStatus.rejected, ReleaseStatus.approved):
        raise DeliveryError(f"Release is {release.status.value}, not awaiting review")
    try:
        assign_codes(session, release)
    except ValueError as exc:
        raise DeliveryError(f"{exc}. Enter the UPC/ISRCs by hand or configure your prefixes.") from exc
    report = check_release(release, require_codes=True)
    if not report.ok:
        raise DeliveryError("; ".join(report.errors))
    release.status = ReleaseStatus.approved
    release.review_notes = None
    session.commit()


def deliver(session: Session, release: Release, target: DeliveryTarget,
            kind: DeliveryKind = DeliveryKind.insert) -> Delivery:
    if not target.active:
        raise DeliveryError(f"Target {target.name} is disabled")
    if kind != DeliveryKind.takedown and release.status not in (ReleaseStatus.approved, ReleaseStatus.delivered):
        raise DeliveryError("Only approved releases can be delivered")

    out_root = settings.outbox_root / target.name
    package = build_package(
        release,
        out_root=out_root,
        recipient_party_id=target.recipient_party_id,
        recipient_name=target.recipient_party_name,
        test_message=target.test_mode,
        takedown=kind == DeliveryKind.takedown,
    )
    delivery = Delivery(
        release=release,
        target=target,
        kind=kind,
        batch_id=package.batch_id,
        message_id=package.message_id,
        package_path=str(package.batch_dir),
    )
    session.add(delivery)
    session.flush()
    try:
        delivery.remote_ref = make_transport(target.transport, target.config or {}).send(package)
        delivery.status = DeliveryStatus.sent
        delivery.sent_at = datetime.now(timezone.utc)
        release.status = ReleaseStatus.taken_down if kind == DeliveryKind.takedown else ReleaseStatus.delivered
    except (TransportError, TypeError) as exc:
        delivery.status = DeliveryStatus.failed
        delivery.error = str(exc)
    session.commit()
    return delivery
