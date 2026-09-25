"""Quality control: catch what stores reject before a release goes out.

Errors block submission. Warnings are style-guide issues that Apple and
Spotify commonly reject for; an admin can still approve them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from .identifiers import is_valid_isrc, is_valid_upc
from .models import Release

BANNED_TITLE_WORDS = re.compile(
    r"\b(official (audio|video|music video)|explicit|clean version|exclusive|free download|hq|lyrics?)\b",
    re.IGNORECASE,
)
FEAT_IN_TITLE = re.compile(r"\b(feat\.?|ft\.?|featuring)\s", re.IGNORECASE)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


@dataclass
class QCReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _title_checks(label: str, title: str, report: QCReport) -> None:
    if FEAT_IN_TITLE.search(title):
        report.warnings.append(f"{label}: put featured artists in credits, not in the title")
    if BANNED_TITLE_WORDS.search(title):
        report.warnings.append(f"{label}: title contains words stores reject (e.g. 'Official Audio', 'Explicit')")
    if EMOJI.search(title):
        report.errors.append(f"{label}: emoji are not allowed in titles")
    letters = [c for c in title if c.isalpha()]
    if len(letters) > 3 and all(c.isupper() for c in letters):
        report.warnings.append(f"{label}: ALL CAPS titles are usually rejected unless stylized that way officially")


def check_release(release: Release, *, require_codes: bool = False) -> QCReport:
    r = QCReport()
    if not release.title.strip():
        r.errors.append("Release title is required")
    _title_checks("Release", release.title, r)
    if not release.genre:
        r.errors.append("Genre is required")
    if not release.p_line or not release.c_line:
        r.errors.append("P-line and C-line (rights holders) are required")
    if not release.artwork_path:
        r.errors.append("Cover art is required (3000x3000 JPEG/PNG)")
    if release.upc and not is_valid_upc(release.upc):
        r.errors.append(f"UPC {release.upc} is not valid")
    elif require_codes and not release.upc:
        r.errors.append("UPC is missing")

    tracks = list(release.tracks)
    if not tracks:
        r.errors.append("Add at least one track")
    n = len(tracks)
    total = sum(t.duration_seconds or 0 for t in tracks)
    if release.release_type.value == "Single" and n > 3:
        r.warnings.append("Singles have 1-3 tracks; this should be an EP or Album")
    if release.release_type.value == "EP" and (n > 6 or total >= 30 * 60):
        r.warnings.append("EPs are 4-6 tracks under 30 minutes; this should be an Album")
    if release.release_type.value == "Album" and n < 7 and total < 30 * 60:
        r.warnings.append("Albums are 7+ tracks or 30+ minutes; this should be an EP or Single")

    for t in tracks:
        label = f"Track {t.track_number} '{t.title}'"
        _title_checks(label, t.title, r)
        if not t.audio_path:
            r.errors.append(f"{label}: audio file is missing")
        if t.isrc and not is_valid_isrc(t.isrc):
            r.errors.append(f"{label}: ISRC {t.isrc} is not valid")
        elif require_codes and not t.isrc:
            r.errors.append(f"{label}: ISRC is missing")
        if not any(c.role in ("Composer", "Lyricist", "ComposerLyricist") for c in t.contributors):
            r.warnings.append(f"{label}: add at least one songwriter credit (required by Spotify and Apple)")
        if not t.splits:
            r.errors.append(f"{label}: add royalty splits (100% to yourself if solo)")
        else:
            total_pct = sum((s.percent for s in t.splits), Decimal(0))
            if total_pct != Decimal(100):
                r.errors.append(f"{label}: splits add up to {total_pct}%, must be exactly 100%")
    return r
