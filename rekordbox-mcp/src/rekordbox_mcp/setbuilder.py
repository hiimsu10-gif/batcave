"""Ordering tracks into a DJ set: BPM ramp + harmonic (Camelot) flow."""

from __future__ import annotations

from .camelot import describe_transition, to_camelot, transition_cost

# Beyond this BPM jump between neighbours a transition needs pitch riding or a cut.
MAX_COMFORTABLE_BPM_JUMP_PCT = 6.0


def _bpm_jump_pct(a: float, b: float) -> float:
    return abs(b - a) / a * 100 if a else 100.0


def _cost(prev: dict, cand: dict, target_bpm: float, recent_artists: list[str]) -> float:
    harmonic = transition_cost(prev.get("camelot"), cand.get("camelot")) * 10
    ramp = abs(cand["bpm"] - target_bpm) / target_bpm * 100 * 1.5
    jump = _bpm_jump_pct(prev["bpm"], cand["bpm"])
    jump_penalty = 0 if jump <= MAX_COMFORTABLE_BPM_JUMP_PCT else (jump - MAX_COMFORTABLE_BPM_JUMP_PCT) * 8
    rating_bonus = (cand.get("rating") or 0) * 1.5
    artist_penalty = 12 if cand.get("artist") and cand["artist"] in recent_artists else 0
    return harmonic + ramp + jump_penalty + artist_penalty - rating_bonus


def build_set(
    tracks: list[dict],
    duration_minutes: float,
    bpm_start: float | None = None,
    bpm_end: float | None = None,
    start_key: str | None = None,
    start_track_id: str | None = None,
) -> dict:
    """Greedily build a set from candidate track dicts.

    Each track needs ``id``, ``bpm`` and ``length_sec``; ``camelot``, ``rating`` and
    ``artist`` improve the ordering. Returns the ordered tracks with transition notes.
    """
    pool = [t for t in tracks if t.get("bpm") and t.get("length_sec")]
    if not pool:
        return {"tracks": [], "total_minutes": 0, "warnings": ["No candidate tracks with BPM and length."]}

    bpms = sorted(t["bpm"] for t in pool)
    bpm_start = bpm_start or bpms[len(bpms) // 4]
    bpm_end = bpm_end or bpm_start
    target_sec = duration_minutes * 60
    start_code = to_camelot(start_key)

    by_id = {str(t["id"]): t for t in pool}
    if start_track_id and str(start_track_id) in by_id:
        first = by_id[str(start_track_id)]
    else:
        def first_cost(t: dict) -> tuple:
            key_pen = 0 if not start_code else transition_cost(start_code, t.get("camelot")) * 10
            return (abs(t["bpm"] - bpm_start) * 3 + key_pen - (t.get("rating") or 0) * 1.5, str(t["id"]))
        first = min(pool, key=first_cost)

    ordered = [first]
    used = {str(first["id"])}
    elapsed = first["length_sec"]
    while elapsed < target_sec:
        remaining = [t for t in pool if str(t["id"]) not in used]
        if not remaining:
            break
        progress = min(elapsed / target_sec, 1.0)
        target_bpm = bpm_start + (bpm_end - bpm_start) * progress
        recent_artists = [t.get("artist") for t in ordered[-3:] if t.get("artist")]
        prev = ordered[-1]
        nxt = min(remaining, key=lambda c: (_cost(prev, c, target_bpm, recent_artists), str(c["id"])))
        ordered.append(nxt)
        used.add(str(nxt["id"]))
        elapsed += nxt["length_sec"]

    out = []
    warnings = []
    clashes = 0
    for i, t in enumerate(ordered):
        entry = dict(t)
        entry["position"] = i + 1
        if i > 0:
            prev = ordered[i - 1]
            jump = round(t["bpm"] - prev["bpm"], 2)
            note = describe_transition(prev.get("camelot"), t.get("camelot"))
            if note == "key clash":
                clashes += 1
            big_jump = _bpm_jump_pct(prev["bpm"], t["bpm"]) > MAX_COMFORTABLE_BPM_JUMP_PCT
            entry["transition"] = (
                f"{prev.get('camelot') or '?'} -> {t.get('camelot') or '?'} ({note}), "
                f"{'+' if jump >= 0 else ''}{jump} BPM" + (" - big tempo jump" if big_jump else "")
            )
        out.append(entry)

    total_minutes = round(elapsed / 60, 1)
    if elapsed < target_sec:
        warnings.append(
            f"Only {total_minutes} of {duration_minutes} minutes could be filled from {len(pool)} candidate tracks."
        )
    if clashes:
        warnings.append(f"{clashes} transition(s) are key clashes; consider a loop/effect or a cut there.")
    return {
        "tracks": out,
        "total_minutes": total_minutes,
        "bpm_start": round(bpm_start, 2),
        "bpm_end": round(bpm_end, 2),
        "warnings": warnings,
    }
