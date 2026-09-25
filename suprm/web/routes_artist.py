from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..identifiers import is_valid_isrc, is_valid_upc, normalize_isrc
from ..media import MediaError, inspect_audio, inspect_image
from ..models import (
    Artist,
    Contributor,
    LedgerEntry,
    Release,
    ReleaseStatus,
    ReleaseType,
    Split,
    Track,
    User,
)
from ..qc import check_release
from ..royalties.ledger import balance, earnings_breakdown
from .app import render
from .deps import current_user, db, flash, owned_release, owned_track, verify_csrf

router = APIRouter()

EDITABLE = (ReleaseStatus.draft, ReleaseStatus.rejected)
CONTRIBUTOR_ROLES = ["MainArtist", "FeaturedArtist", "Composer", "Lyricist", "ComposerLyricist",
                     "Producer", "Remixer", "Arranger"]
GENRES = ["Alternative", "Blues", "Children's Music", "Christian & Gospel", "Classical", "Country", "Dance",
          "Electronic", "Folk", "Hip-Hop/Rap", "Jazz", "K-Pop", "Latin", "Metal", "Pop", "R&B/Soul",
          "Reggae", "Rock", "Singer/Songwriter", "Soundtrack", "World", "Afrobeats", "Amapiano", "Reggaeton"]
MAX_AUDIO_BYTES = 2 * 1024**3
MAX_IMAGE_BYTES = 50 * 1024**2


def _back(release_id: int) -> RedirectResponse:
    return RedirectResponse(f"/releases/{release_id}", status_code=303)


def _require_editable(release: Release) -> None:
    if release.status not in EDITABLE:
        raise HTTPException(400, "This release is locked while it's in review or live. Contact support to change it.")


async def _save_upload(upload: UploadFile, user: User, max_bytes: int) -> Path:
    """Stream an upload to MEDIA_ROOT/<user>/<uuid><ext>; returns the path relative to MEDIA_ROOT."""
    ext = Path(upload.filename or "").suffix.lower()[:6]
    rel = Path(str(user.id)) / f"{uuid.uuid4().hex}{ext}"
    dest = settings.media_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with open(dest, "wb") as out:
        while chunk := await upload.read(1 << 20):
            size += len(chunk)
            if size > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)
                raise MediaError("File is too large")
            out.write(chunk)
    return rel


def _discard(rel: str | None) -> None:
    if rel:
        (settings.media_root / rel).unlink(missing_ok=True)


# --- Dashboard ---------------------------------------------------------------

@router.get("/dashboard")
def dashboard(request: Request, user: User = Depends(current_user), session: Session = Depends(db)):
    releases = session.scalars(
        select(Release).join(Artist).where(Artist.owner_id == user.id).order_by(Release.created_at.desc())
    ).all()
    top_stores = earnings_breakdown(session, user.id, "store")[:5]
    lifetime = session.scalar(
        select(func.sum(LedgerEntry.amount)).where(LedgerEntry.user_id == user.id, LedgerEntry.kind == "royalty")
    ) or Decimal(0)
    return render(request, "dashboard.html", user=user, releases=releases, balance=balance(session, user.id),
                  lifetime=lifetime, top_stores=top_stores)


@router.get("/earnings")
def earnings(request: Request, by: str = "store", user: User = Depends(current_user),
             session: Session = Depends(db)):
    if by not in ("store", "territory", "period", "track"):
        by = "store"
    rows = earnings_breakdown(session, user.id, by)
    entries = session.scalars(
        select(LedgerEntry).where(LedgerEntry.user_id == user.id).order_by(LedgerEntry.id.desc()).limit(200)
    ).all()
    return render(request, "earnings.html", user=user, by=by, rows=rows, entries=entries,
                  balance=balance(session, user.id))


# --- Releases ----------------------------------------------------------------

@router.get("/releases/new")
def new_release_form(request: Request, user: User = Depends(current_user)):
    return render(request, "release_new.html", user=user, genres=GENRES, types=list(ReleaseType),
                  today=date.today(), label=settings.default_label_name)


@router.post("/releases/new", dependencies=[Depends(verify_csrf)])
def create_release(
    request: Request,
    artist_id: int = Form(...),
    title: str = Form(...),
    release_type: ReleaseType = Form(ReleaseType.Single),
    genre: str = Form(...),
    release_date: date = Form(...),
    label_name: str = Form(""),
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    artist = session.get(Artist, artist_id)
    if not artist or artist.owner_id != user.id:
        raise HTTPException(404, "Artist not found")
    year = release_date.year
    rights_holder = label_name.strip() or artist.name
    release = Release(
        artist=artist, title=title.strip(), release_type=release_type, genre=genre,
        release_date=release_date, label_name=label_name.strip() or settings.default_label_name,
        p_line_year=year, p_line=rights_holder, c_line_year=year, c_line=rights_holder,
    )
    session.add(release)
    session.commit()
    if (release_date - date.today()).days < 14:
        flash(request, "Tip: set your release date 3-4 weeks out so you can pitch to Spotify editorial.", "info")
    return _back(release.id)


@router.get("/releases/{release_id}")
def release_page(release_id: int, request: Request, user: User = Depends(current_user),
                 session: Session = Depends(db)):
    release = owned_release(release_id, user, session)
    return render(request, "release.html", user=user, release=release, report=check_release(release),
                  editable=release.status in EDITABLE, genres=GENRES, types=list(ReleaseType),
                  roles=CONTRIBUTOR_ROLES)


@router.post("/releases/{release_id}", dependencies=[Depends(verify_csrf)])
def update_release(
    release_id: int,
    request: Request,
    title: str = Form(...),
    version: str = Form(""),
    release_type: ReleaseType = Form(...),
    genre: str = Form(...),
    subgenre: str = Form(""),
    language: str = Form("en"),
    release_date: date = Form(...),
    original_release_date: str = Form(""),
    label_name: str = Form(...),
    p_line: str = Form(...),
    c_line: str = Form(...),
    explicit: bool = Form(False),
    territories: str = Form("Worldwide"),
    upc: str = Form(""),
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    release = owned_release(release_id, user, session)
    _require_editable(release)
    upc = upc.strip()
    if upc and (not is_valid_upc(upc) or session.scalar(
            select(Release.id).where(Release.upc == upc, Release.id != release.id))):
        flash(request, f"UPC {upc} is invalid or already used by another release", "error")
        return _back(release.id)
    release.title, release.version = title.strip(), version.strip() or None
    release.release_type, release.genre, release.subgenre = release_type, genre, subgenre.strip() or None
    release.language = language.strip()[:8] or "en"
    release.release_date = release_date
    release.original_release_date = date.fromisoformat(original_release_date) if original_release_date else None
    release.label_name, release.p_line, release.c_line = label_name.strip(), p_line.strip(), c_line.strip()
    release.p_line_year = release.c_line_year = (release.original_release_date or release_date).year
    release.explicit = explicit
    release.territories = territories.strip() or "Worldwide"
    release.upc = upc or None  # artists who already own a UPC can bring it
    session.commit()
    flash(request, "Release saved", "success")
    return _back(release.id)


@router.post("/releases/{release_id}/artwork", dependencies=[Depends(verify_csrf)])
async def upload_artwork(release_id: int, request: Request, file: UploadFile,
                         user: User = Depends(current_user), session: Session = Depends(db)):
    release = owned_release(release_id, user, session)
    _require_editable(release)
    try:
        rel = await _save_upload(file, user, MAX_IMAGE_BYTES)
        try:
            inspect_image(settings.media_root / rel)
        except MediaError:
            _discard(str(rel))
            raise
    except MediaError as exc:
        flash(request, str(exc), "error")
        return _back(release.id)
    _discard(release.artwork_path)
    release.artwork_path = str(rel)
    session.commit()
    flash(request, "Cover art uploaded", "success")
    return _back(release.id)


@router.post("/releases/{release_id}/submit", dependencies=[Depends(verify_csrf)])
def submit_release(release_id: int, request: Request, user: User = Depends(current_user),
                   session: Session = Depends(db)):
    release = owned_release(release_id, user, session)
    _require_editable(release)
    report = check_release(release)
    if not report.ok:
        flash(request, "Fix the errors below before submitting", "error")
        return _back(release.id)
    release.status = ReleaseStatus.in_review
    session.commit()
    flash(request, "Submitted! We'll review it and send it to stores.", "success")
    return _back(release.id)


@router.post("/releases/{release_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_release(release_id: int, request: Request, user: User = Depends(current_user),
                   session: Session = Depends(db)):
    release = owned_release(release_id, user, session)
    if release.status != ReleaseStatus.draft:
        raise HTTPException(400, "Only drafts can be deleted")
    for t in release.tracks:
        _discard(t.audio_path)
    _discard(release.artwork_path)
    session.delete(release)
    session.commit()
    flash(request, "Draft deleted", "success")
    return RedirectResponse("/dashboard", status_code=303)


# --- Tracks ------------------------------------------------------------------

@router.post("/releases/{release_id}/tracks", dependencies=[Depends(verify_csrf)])
async def add_track(
    release_id: int,
    request: Request,
    file: UploadFile,
    title: str = Form(...),
    version: str = Form(""),
    explicit: bool = Form(False),
    isrc: str = Form(""),
    songwriter: str = Form(""),
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    release = owned_release(release_id, user, session)
    _require_editable(release)
    if isrc and not is_valid_isrc(isrc):
        flash(request, f"ISRC {isrc} is not valid (format: CC-XXX-YY-NNNNN)", "error")
        return _back(release.id)
    try:
        rel = await _save_upload(file, user, MAX_AUDIO_BYTES)
        try:
            info = inspect_audio(settings.media_root / rel)
        except MediaError:
            _discard(str(rel))
            raise
    except MediaError as exc:
        flash(request, str(exc), "error")
        return _back(release.id)
    track = Track(
        release=release,
        track_number=len(release.tracks) + 1,
        title=title.strip(),
        version=version.strip() or None,
        explicit=explicit,
        isrc=normalize_isrc(isrc) if isrc else None,
        audio_path=str(rel),
        audio_codec=info.codec,
        duration_seconds=info.duration_seconds,
    )
    track.contributors.append(Contributor(name=release.artist.name, role="MainArtist"))
    if songwriter.strip():
        track.contributors.append(Contributor(name=songwriter.strip(), role="ComposerLyricist"))
    track.splits.append(Split(user_id=user.id, email=user.email, percent=Decimal(100)))
    session.add(track)
    session.commit()
    flash(request, f"Added '{track.title}' ({info.codec}, {info.sample_rate} Hz, {info.bits_per_sample}-bit)",
          "success")
    return _back(release.id)


@router.post("/tracks/{track_id}", dependencies=[Depends(verify_csrf)])
def update_track(
    track_id: int,
    request: Request,
    title: str = Form(...),
    version: str = Form(""),
    explicit: bool = Form(False),
    isrc: str = Form(""),
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    track = owned_track(track_id, user, session)
    _require_editable(track.release)
    if isrc and not is_valid_isrc(isrc):
        flash(request, f"ISRC {isrc} is not valid", "error")
        return _back(track.release_id)
    track.title, track.version, track.explicit = title.strip(), version.strip() or None, explicit
    track.isrc = normalize_isrc(isrc) if isrc else None
    session.commit()
    return _back(track.release_id)


@router.post("/tracks/{track_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_track(track_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    track = owned_track(track_id, user, session)
    release = track.release
    _require_editable(release)
    _discard(track.audio_path)
    release.tracks.remove(track)
    session.flush()
    # Renumber in two passes so the (release, track_number) unique constraint never trips.
    for i, t in enumerate(release.tracks, start=1):
        t.track_number = 1000 + i
    session.flush()
    for t in release.tracks:
        t.track_number -= 1000
    session.commit()
    return _back(release.id)


@router.post("/tracks/{track_id}/contributors", dependencies=[Depends(verify_csrf)])
def add_contributor(track_id: int, name: str = Form(...), role: str = Form(...),
                    user: User = Depends(current_user), session: Session = Depends(db)):
    track = owned_track(track_id, user, session)
    _require_editable(track.release)
    if role not in CONTRIBUTOR_ROLES:
        raise HTTPException(400, "Unknown role")
    track.contributors.append(Contributor(name=name.strip(), role=role))
    session.commit()
    return _back(track.release_id)


@router.post("/contributors/{cid}/delete", dependencies=[Depends(verify_csrf)])
def delete_contributor(cid: int, user: User = Depends(current_user), session: Session = Depends(db)):
    contributor = session.get(Contributor, cid)
    if not contributor:
        raise HTTPException(404)
    track = owned_track(contributor.track_id, user, session)
    _require_editable(track.release)
    session.delete(contributor)
    session.commit()
    return _back(track.release_id)


@router.post("/tracks/{track_id}/splits", dependencies=[Depends(verify_csrf)])
def add_split(track_id: int, request: Request, email: str = Form(...), percent: str = Form(...),
              user: User = Depends(current_user), session: Session = Depends(db)):
    track = owned_track(track_id, user, session)
    _require_editable(track.release)
    try:
        pct = Decimal(percent.strip().rstrip("%"))
    except InvalidOperation:
        pct = Decimal(-1)
    if not Decimal(0) < pct <= Decimal(100):
        flash(request, "Split percent must be between 0 and 100", "error")
        return _back(track.release_id)
    email = email.strip().lower()
    payee = session.scalar(select(User).where(func.lower(User.email) == email))
    existing = next((s for s in track.splits if s.email.lower() == email), None)
    if existing:
        existing.percent = pct
    else:
        track.splits.append(Split(email=email, user_id=payee.id if payee else None, percent=pct))
    session.commit()
    total = sum((s.percent for s in track.splits), Decimal(0))
    if total != 100:
        flash(request, f"Splits on '{track.title}' now total {total}%. Adjust them to reach exactly 100%.", "info")
    return _back(track.release_id)


@router.post("/splits/{split_id}/delete", dependencies=[Depends(verify_csrf)])
def delete_split(split_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    split = session.get(Split, split_id)
    if not split:
        raise HTTPException(404)
    track = owned_track(split.track_id, user, session)
    _require_editable(track.release)
    session.delete(split)
    session.commit()
    return _back(track.release_id)


# --- Protected media (for previews and admin QC) -----------------------------

@router.get("/files/artwork/{release_id}")
def artwork_file(release_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    release = owned_release(release_id, user, session)
    if not release.artwork_path:
        raise HTTPException(404)
    return FileResponse(settings.media_root / release.artwork_path)


@router.get("/files/audio/{track_id}")
def audio_file(track_id: int, user: User = Depends(current_user), session: Session = Depends(db)):
    track = owned_track(track_id, user, session)
    if not track.audio_path:
        raise HTTPException(404)
    return FileResponse(settings.media_root / track.audio_path)
