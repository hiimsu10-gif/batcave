#!/usr/bin/env python3
"""Check the ITR set lists against Su's Rekordbox library and local Dropbox files.

Run on the Mac (not in the cloud), with Rekordbox closed:

    pip3 install pyrekordbox
    python3 tools/rekordbox_itr_check.py                 # report only
    python3 tools/rekordbox_itr_check.py --download      # also pull down online-only files

For every track in the ITR set lists it reports:
  - whether it's in the Rekordbox collection, with Rekordbox's own key and BPM
  - whether the audio file is on disk, online-only (Dropbox placeholder), or missing

The report is written next to the set lists as "ITR Rekordbox Check.md".
"""

import argparse
import os
import re
import sys
import unicodedata
from pathlib import Path

DROPBOX = Path.home() / "Library/CloudStorage/Dropbox-ProfessionalDJteam/Su/Music Collection"
SETLISTS = DROPBOX / "Setlists"
LIBRARY = DROPBOX / "Main Library"
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aiff", ".aif", ".flac"}
ROW = re.compile(r"^\| (\d+) \| (.+?) \|")
EPISODE = re.compile(r"^## ITR (Ep\d+)")


def norm(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def key_words(track):
    """Distinctive words from a set-list title, ignoring features, remix tags and notes."""
    title = track.split(" – ", 1)[-1]
    title = re.sub(r"\*.*?\*|⚠️", "", title)
    core = re.sub(r"\(.*?\)|\[.*?\]|\bft\..*|\bfeat\..*", "", title)
    words = [w for w in norm(core).split() if len(w) > 2]
    return words or norm(title).split()


def read_setlists(folder):
    tracks = []
    for doc in sorted(folder.glob("ITR Ep*Setlists.md")):
        episode = None
        for line in doc.read_text(encoding="utf-8").splitlines():
            m = EPISODE.match(line)
            if m:
                episode = m.group(1)
                continue
            m = ROW.match(line)
            if m and episode:
                tracks.append({"ep": episode, "n": int(m.group(1)), "track": m.group(2).strip()})
    return tracks


def file_status(path):
    """'on disk', 'online-only' (Dropbox placeholder with no local data) or 'missing'."""
    if not path or not os.path.exists(path):
        return "missing"
    return "on disk" if os.stat(path).st_blocks > 0 else "online-only"


def download(path):
    """Reading a placeholder makes the Dropbox File Provider download it."""
    with open(path, "rb") as f:
        while f.read(1 << 20):
            pass


def load_rekordbox():
    try:
        from pyrekordbox import Rekordbox6Database
    except ImportError:
        sys.exit("pyrekordbox isn't installed. Run: pip3 install pyrekordbox")
    try:
        db = Rekordbox6Database()
    except Exception as e:  # key or version problems surface here
        sys.exit(f"Couldn't open the Rekordbox database ({e}).\n"
                 "Close Rekordbox and try again. On Rekordbox 7 you may first need: "
                 "python3 -m pyrekordbox download-key")
    items = []
    for c in db.get_content():
        artist = getattr(c, "ArtistName", None) or getattr(getattr(c, "Artist", None), "Name", "")
        key = getattr(c, "KeyName", None) or getattr(getattr(c, "Key", None), "ScaleName", "")
        bpm = (c.BPM or 0) / 100
        path = c.FolderPath or ""
        items.append({
            "text": norm(f"{artist} {c.Title} {Path(path).stem}"),
            "key": key or "—",
            "bpm": f"{bpm:.0f}" if bpm else "—",
            "path": path,
        })
    return items


def index_library(folder):
    return [(norm(p.stem), str(p)) for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXT]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setlists", type=Path, default=SETLISTS)
    ap.add_argument("--library", type=Path, default=LIBRARY)
    ap.add_argument("--download", action="store_true", help="download online-only files in the set lists")
    args = ap.parse_args()

    tracks = read_setlists(args.setlists)
    if not tracks:
        sys.exit(f"No ITR set lists found in {args.setlists}")
    rb = load_rekordbox()
    files = index_library(args.library)

    rows, counts = [], {"in rekordbox": 0, "not imported": 0, "on disk": 0, "online-only": 0, "missing": 0}
    for t in tracks:
        words = key_words(t["track"])
        hit = next((r for r in rb if all(w in r["text"] for w in words)), None)
        path = hit["path"] if hit else next((p for name, p in files if all(w in name for w in words)), "")
        status = file_status(path)
        if status == "online-only" and args.download:
            download(path)
            status = file_status(path)
        counts["in rekordbox" if hit else "not imported"] += 1
        counts[status] += 1
        rows.append((t, hit, status, path))

    out = args.setlists / "ITR Rekordbox Check.md"
    lines = ["# ITR Rekordbox Check", "",
             f"{len(tracks)} tracks · in Rekordbox: {counts['in rekordbox']} · not imported: {counts['not imported']}"
             f" · on disk: {counts['on disk']} · online-only: {counts['online-only']} · missing: {counts['missing']}", ""]
    episode = None
    for t, hit, status, path in rows:
        if t["ep"] != episode:
            episode = t["ep"]
            lines += ["", f"## {episode}", "", "| # | Track | Rekordbox | Key | BPM | File |", "|---|---|---|---|---|---|"]
        lines.append(f"| {t['n']} | {t['track']} | {'yes' if hit else '**not imported**'} | "
                     f"{hit['key'] if hit else '—'} | {hit['bpm'] if hit else '—'} | {status} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(lines[2])
    print(f"Report: {out}")


if __name__ == "__main__":
    main()
