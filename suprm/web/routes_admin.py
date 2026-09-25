from __future__ import annotations

import json
from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..delivery.service import DeliveryError, approve_release, deliver
from ..delivery.transports import TRANSPORTS
from ..models import (
    Delivery,
    DeliveryKind,
    DeliveryTarget,
    Payout,
    Release,
    ReleaseStatus,
    RoyaltyLine,
    RoyaltyStatement,
    User,
)
from ..payouts.stripe_connect import PaymentError, payable_amount, run_payouts
from ..qc import check_release
from ..royalties.importer import ImportError_, import_report
from ..royalties.ledger import allocate_statement, platform_revenue, rematch_unmatched, unclaimed_total
from . import routes_payouts
from .app import render
from .deps import admin_user, db, flash, verify_csrf

router = APIRouter(dependencies=[Depends(admin_user)])


@router.get("")
def overview(request: Request, session: Session = Depends(db)):
    in_review = session.scalars(select(Release).where(Release.status == ReleaseStatus.in_review)
                                .order_by(Release.updated_at)).all()
    approved = session.scalars(select(Release).where(Release.status == ReleaseStatus.approved)).all()
    recent = session.scalars(select(Delivery).order_by(Delivery.id.desc()).limit(20)).all()
    stats = {
        "artists": session.scalar(select(func.count(User.id))),
        "live": session.scalar(select(func.count(Release.id)).where(Release.status == ReleaseStatus.delivered)),
        "unmatched": session.scalar(select(func.count(RoyaltyLine.id)).where(RoyaltyLine.track_id.is_(None))),
        "platform_revenue": platform_revenue(session),
        "unclaimed": unclaimed_total(session),
    }
    return render(request, "admin/overview.html", in_review=in_review, approved=approved, recent=recent,
                  stats=stats)


# --- Release review & delivery ----------------------------------------------

@router.get("/releases/{release_id}")
def review(release_id: int, request: Request, session: Session = Depends(db)):
    release = session.get(Release, release_id) or _404()
    targets = session.scalars(select(DeliveryTarget).where(DeliveryTarget.active.is_(True))).all()
    return render(request, "admin/review.html", release=release, report=check_release(release), targets=targets)


@router.post("/releases/{release_id}/approve", dependencies=[Depends(verify_csrf)])
def approve(release_id: int, request: Request, session: Session = Depends(db)):
    release = session.get(Release, release_id) or _404()
    try:
        approve_release(session, release)
        flash(request, f"Approved. UPC {release.upc}.", "success")
    except DeliveryError as exc:
        session.rollback()
        flash(request, str(exc), "error")
    return RedirectResponse(f"/admin/releases/{release_id}", status_code=303)


@router.post("/releases/{release_id}/reject", dependencies=[Depends(verify_csrf)])
def reject(release_id: int, request: Request, notes: str = Form(...), session: Session = Depends(db)):
    release = session.get(Release, release_id) or _404()
    release.status = ReleaseStatus.rejected
    release.review_notes = notes.strip()
    session.commit()
    flash(request, "Sent back to the artist", "success")
    return RedirectResponse("/admin", status_code=303)


@router.post("/releases/{release_id}/deliver", dependencies=[Depends(verify_csrf)])
def deliver_release(release_id: int, request: Request, target_ids: list[int] = Form(...),
                    kind: DeliveryKind = Form(DeliveryKind.insert), session: Session = Depends(db)):
    release = session.get(Release, release_id) or _404()
    for tid in target_ids:
        target = session.get(DeliveryTarget, tid)
        if not target:
            continue
        try:
            d = deliver(session, release, target, kind)
            if d.status.value == "failed":
                flash(request, f"{target.name}: failed - {d.error}", "error")
            else:
                flash(request, f"{target.name}: {kind.value} sent ({d.remote_ref})", "success")
        except (DeliveryError, ValueError) as exc:
            session.rollback()
            flash(request, f"{target.name}: {exc}", "error")
    return RedirectResponse(f"/admin/releases/{release_id}", status_code=303)


# --- Delivery targets --------------------------------------------------------

@router.get("/targets")
def targets(request: Request, session: Session = Depends(db)):
    rows = session.scalars(select(DeliveryTarget).order_by(DeliveryTarget.name)).all()
    return render(request, "admin/targets.html", targets=rows, transports=list(TRANSPORTS))


@router.post("/targets", dependencies=[Depends(verify_csrf)])
def create_target(
    request: Request,
    name: str = Form(...),
    transport: str = Form(...),
    recipient_party_id: str = Form(...),
    recipient_party_name: str = Form(...),
    config_json: str = Form("{}"),
    session: Session = Depends(db),
):
    if transport not in TRANSPORTS:
        raise HTTPException(400, "Unknown transport")
    try:
        config = json.loads(config_json or "{}")
        assert isinstance(config, dict)
    except (ValueError, AssertionError):
        flash(request, "Config must be a JSON object", "error")
        return RedirectResponse("/admin/targets", status_code=303)
    session.add(DeliveryTarget(name=name.strip(), transport=transport, config=config,
                               recipient_party_id=recipient_party_id.strip(),
                               recipient_party_name=recipient_party_name.strip()))
    session.commit()
    flash(request, f"Added {name}. It starts in TEST mode.", "success")
    return RedirectResponse("/admin/targets", status_code=303)


@router.post("/targets/{target_id}/toggle", dependencies=[Depends(verify_csrf)])
def toggle_target(target_id: int, field: str = Form(...), session: Session = Depends(db)):
    target = session.get(DeliveryTarget, target_id) or _404()
    if field == "active":
        target.active = not target.active
    elif field == "test_mode":
        target.test_mode = not target.test_mode
    session.commit()
    return RedirectResponse("/admin/targets", status_code=303)


# --- Royalties ---------------------------------------------------------------

@router.get("/royalties")
def royalties(request: Request, session: Session = Depends(db)):
    statements = session.scalars(select(RoyaltyStatement).order_by(RoyaltyStatement.id.desc())).all()
    return render(request, "admin/royalties.html", statements=statements)


@router.post("/royalties", dependencies=[Depends(verify_csrf)])
async def upload_report(request: Request, file: UploadFile, source: str = Form(...), period: str = Form(...),
                        currency: str = Form("USD"), session: Session = Depends(db)):
    content = await file.read()
    try:
        result = import_report(session, content, source=source.strip(), period=period.strip(),
                               filename=file.filename or "report.csv", currency=currency.strip().upper())
    except ImportError_ as exc:
        session.rollback()
        flash(request, str(exc), "error")
        return RedirectResponse("/admin/royalties", status_code=303)
    st = result.statement
    if result.duplicate:
        flash(request, f"That file was already imported (statement #{st.id})", "info")
    else:
        flash(request, f"Imported {st.line_count} lines, ${st.gross_amount:,.2f} gross, "
                       f"{st.unmatched_count} unmatched. Review, then click Allocate.", "success")
    return RedirectResponse(f"/admin/royalties/{st.id}", status_code=303)


@router.get("/royalties/{statement_id}")
def statement_detail(statement_id: int, request: Request, session: Session = Depends(db)):
    st = session.get(RoyaltyStatement, statement_id) or _404()
    unmatched = session.scalars(select(RoyaltyLine).where(RoyaltyLine.statement_id == st.id,
                                                          RoyaltyLine.track_id.is_(None)).limit(500)).all()
    pending = session.scalar(select(func.count(RoyaltyLine.id)).where(
        RoyaltyLine.statement_id == st.id, RoyaltyLine.allocated.is_(False), RoyaltyLine.track_id.is_not(None)))
    return render(request, "admin/statement.html", st=st, unmatched=unmatched, pending=pending)


@router.post("/royalties/{statement_id}/allocate", dependencies=[Depends(verify_csrf)])
def allocate(statement_id: int, request: Request, session: Session = Depends(db)):
    st = session.get(RoyaltyStatement, statement_id) or _404()
    rematch_unmatched(session)
    n = allocate_statement(session, st)
    flash(request, f"Allocated {n} lines to artist balances", "success")
    return RedirectResponse(f"/admin/royalties/{statement_id}", status_code=303)


# --- Payouts -----------------------------------------------------------------

@router.get("/payouts")
def payouts(request: Request, session: Session = Depends(db)):
    users = session.scalars(select(User).order_by(User.display_name)).all()
    owed = [(u, payable_amount(session, u)) for u in users]
    owed = [(u, amt) for u, amt in owed if amt > 0]
    history = session.scalars(select(Payout).order_by(Payout.id.desc()).limit(100)).all()
    total = sum((amt for _, amt in owed), Decimal(0))
    return render(request, "admin/payouts.html", owed=owed, total=total, history=history)


@router.post("/payouts/run", dependencies=[Depends(verify_csrf)])
def payouts_run(request: Request, session: Session = Depends(db)):
    try:
        done = run_payouts(session, routes_payouts.gateway())
    except PaymentError as exc:
        flash(request, str(exc), "error")
        return RedirectResponse("/admin/payouts", status_code=303)
    paid = [p for p in done if p.status.value == "paid"]
    failed = [p for p in done if p.status.value == "failed"]
    flash(request, f"Paid {len(paid)} artists (${sum((p.amount for p in paid), Decimal(0)):,.2f}); "
                   f"{len(failed)} failed", "success" if not failed else "error")
    return RedirectResponse("/admin/payouts", status_code=303)


def _404():
    raise HTTPException(404, "Not found")
