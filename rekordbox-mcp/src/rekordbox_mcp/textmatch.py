"""Normalizing and fuzzy-matching track titles and artist names."""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Iterable

_MIX_NOISE = re.compile(r"\((original|original mix|extended|extended mix|radio edit|clean|dirty|explicit)\)", re.I)
_FEAT = re.compile(r"\b(feat\.?|ft\.?|featuring)\b.*", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def normalize_title(title: str | None) -> str:
    """Lowercase, strip accents, "(Original Mix)" style noise, featured artists and punctuation."""
    if not title:
        return ""
    text = _MIX_NOISE.sub(" ", _fold(title))
    text = _FEAT.sub(" ", text)
    return _NON_ALNUM.sub(" ", text).strip()


def normalize_artist(artist: str | None) -> str:
    if not artist:
        return ""
    text = _FEAT.sub(" ", _fold(artist))
    text = re.sub(r"\s*(&|,|\band\b|\bx\b|\bvs\.?)\s*", " ", text)
    return _NON_ALNUM.sub(" ", text).strip()


def artist_tokens(artist: str | None) -> set[str]:
    return set(normalize_artist(artist).split())


def split_artist_title(text: str) -> tuple[str, str]:
    """Split "Artist - Title" (as in a filename or a pasted tracklist). Artist may be empty."""
    text = text.strip()
    text = re.sub(r"^\d{1,3}[\s._-]+(?=\D)", "", text)  # leading track numbers "01 - "
    for sep in (" - ", " – ", " — ", " -- "):
        if sep in text:
            artist, title = text.split(sep, 1)
            return artist.strip(), title.strip()
    return "", text


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def best_matches(
    artist: str,
    title: str,
    candidates: Iterable[dict],
    min_score: float = 0.75,
    limit: int = 3,
) -> list[tuple[float, dict]]:
    """Score library tracks (dicts with ``title``/``artist``) against a wanted track."""
    want_title = normalize_title(title)
    want_artist = artist_tokens(artist)
    scored = []
    for track in candidates:
        t_score = similarity(want_title, normalize_title(track.get("title")))
        if t_score < min_score - 0.15:
            continue
        have_artist = artist_tokens(track.get("artist")) | artist_tokens(track.get("remixer"))
        if want_artist and have_artist:
            a_score = len(want_artist & have_artist) / len(want_artist)
        else:
            a_score = 0.5  # unknown artist on one side: neither reward nor punish much
        score = 0.7 * t_score + 0.3 * a_score
        if score >= min_score:
            scored.append((round(score, 3), track))
    scored.sort(key=lambda s: (-s[0], str(s[1].get("id"))))
    return scored[:limit]
