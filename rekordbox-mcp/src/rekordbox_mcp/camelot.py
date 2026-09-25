"""Musical key parsing and Camelot-wheel harmonic mixing rules."""

from __future__ import annotations

import re

# Classic key name -> Camelot code. Enharmonic spellings map to the same code.
_CLASSIC_TO_CAMELOT = {
    # minor keys (A)
    "G#m": "1A", "Abm": "1A",
    "D#m": "2A", "Ebm": "2A",
    "A#m": "3A", "Bbm": "3A",
    "Fm": "4A",
    "Cm": "5A",
    "Gm": "6A",
    "Dm": "7A",
    "Am": "8A",
    "Em": "9A",
    "Bm": "10A",
    "F#m": "11A", "Gbm": "11A",
    "C#m": "12A", "Dbm": "12A",
    # major keys (B)
    "B": "1B", "Cb": "1B",
    "F#": "2B", "Gb": "2B",
    "C#": "3B", "Db": "3B",
    "G#": "4B", "Ab": "4B",
    "D#": "5B", "Eb": "5B",
    "A#": "6B", "Bb": "6B",
    "F": "7B",
    "C": "8B",
    "G": "9B",
    "D": "10B",
    "A": "11B",
    "E": "12B",
}

_CAMELOT_TO_CLASSIC = {}
for _name, _code in _CLASSIC_TO_CAMELOT.items():
    _CAMELOT_TO_CLASSIC.setdefault(_code, _name)

_CAMELOT_RE = re.compile(r"^0?([1-9]|1[0-2])\s*([ABab])$")
_CLASSIC_RE = re.compile(
    r"^([A-Ga-g])\s*([#♯b♭]?)\s*(m|min|minor|maj|major)?$", re.IGNORECASE
)


def to_camelot(key: str | None) -> str | None:
    """Convert a key in Camelot ("8A") or classic ("Am", "F# minor") notation.

    Returns the Camelot code, or None when the key can't be parsed.
    """
    if not key:
        return None
    text = key.strip()
    m = _CAMELOT_RE.match(text)
    if m:
        return f"{int(m.group(1))}{m.group(2).upper()}"
    m = _CLASSIC_RE.match(text)
    if not m:
        return None
    note = m.group(1).upper()
    accidental = {"♯": "#", "♭": "b", "B": "b"}.get(m.group(2), m.group(2))
    quality = (m.group(3) or "").lower()
    minor = quality in ("m", "min", "minor")
    return _CLASSIC_TO_CAMELOT.get(f"{note}{accidental}{'m' if minor else ''}")


def to_classic(camelot: str | None) -> str | None:
    code = to_camelot(camelot)
    return _CAMELOT_TO_CLASSIC.get(code) if code else None


def _split(code: str) -> tuple[int, str]:
    return int(code[:-1]), code[-1]


def _wheel_distance(a: int, b: int) -> int:
    d = abs(a - b) % 12
    return min(d, 12 - d)


def compatible_keys(key: str | None) -> list[str]:
    """Keys that mix harmonically with ``key``: itself, +/-1 on the wheel, relative major/minor."""
    code = to_camelot(key)
    if not code:
        return []
    num, letter = _split(code)
    other = "B" if letter == "A" else "A"
    up = num % 12 + 1
    down = (num - 2) % 12 + 1
    return [code, f"{up}{letter}", f"{down}{letter}", f"{num}{other}"]


def transition_cost(a: str | None, b: str | None) -> int:
    """How harmonically rough a transition is.

    0 = same key, 1 = adjacent / relative (the classic safe mixes),
    2 = energy boost (+2) or diagonal move, 4 = clash, 3 = unknown key.
    """
    ca, cb = to_camelot(a), to_camelot(b)
    if not ca or not cb:
        return 3
    na, la = _split(ca)
    nb, lb = _split(cb)
    dist = _wheel_distance(na, nb)
    if la == lb:
        return {0: 0, 1: 1, 2: 2}.get(dist, 4)
    # letter change
    return {0: 1, 1: 2}.get(dist, 4)


def describe_transition(a: str | None, b: str | None) -> str:
    cost = transition_cost(a, b)
    return {
        0: "same key",
        1: "harmonic",
        2: "energy shift",
        3: "key unknown",
        4: "key clash",
    }[cost]
