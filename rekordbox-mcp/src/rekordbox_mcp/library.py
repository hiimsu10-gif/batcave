"""Access to the Rekordbox 6/7 library (master.db) with safe, backed-up writes."""

from __future__ import annotations

import datetime as dt
import os
import shutil
import unicodedata
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from pyrekordbox import Rekordbox6Database
from pyrekordbox.db6 import tables
from pyrekordbox.utils import get_rekordbox_pid

from . import discovery
from .camelot import compatible_keys, to_camelot
from .textmatch import (
    best_matches,
    normalize_artist,
    normalize_title,
    split_artist_title,
)

AUDIO_EXTENSIONS = {".mp3", ".wav", ".aiff", ".aif", ".flac", ".m4a", ".aac", ".alac", ".ogg"}
# Extensions pyrekordbox can register directly (it derives the file type from the suffix).
IMPORTABLE_EXTENSIONS = {".mp3", ".wav", ".aiff", ".flac", ".m4a"}
FILE_TYPE_NAMES = {1: "MP3", 4: "M4A", 5: "FLAC", 11: "WAV", 12: "AIFF"}
LOSSLESS_TYPES = {"FLAC", "WAV", "AIFF"}
PLAYLIST_KIND = {0: "playlist", 1: "folder", 4: "smart playlist"}
MAX_BACKUPS = 30


class LibraryError(Exception):
    """An error with a message meant for the user."""


def rekordbox_running() -> bool:
    return bool(get_rekordbox_pid())


def _nfc(path: str) -> str:
    # macOS stores filenames decomposed (NFD); Rekordbox stores whatever it was given.
    return unicodedata.normalize("NFC", os.path.normcase(path))


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _date(value: Any) -> str | None:
    if not value:
        return None
    return str(value)[:10]


def _stars(rating: Any) -> int:
    r = _as_int(rating)
    return r if r <= 5 else round(r / 51)  # tolerate the 0-255 scale used in XML exports


def _fmt_len(sec: int) -> str:
    return f"{sec // 60}:{sec % 60:02d}"


@dataclass
class Config:
    db_path: Path | None = None
    backup_dir: Path = field(default_factory=lambda: Path.home() / "Documents" / "rekordbox-mcp-backups")
    downloads_dir: Path | None = None
    unlock: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        env = os.environ
        cfg = cls()
        if env.get("REKORDBOX_DB_PATH"):
            cfg.db_path = Path(env["REKORDBOX_DB_PATH"]).expanduser()
        if env.get("REKORDBOX_MCP_BACKUP_DIR"):
            cfg.backup_dir = Path(env["REKORDBOX_MCP_BACKUP_DIR"]).expanduser()
        if env.get("REKORDBOX_MCP_DOWNLOADS_DIR"):
            cfg.downloads_dir = Path(env["REKORDBOX_MCP_DOWNLOADS_DIR"]).expanduser()
        cfg.unlock = env.get("REKORDBOX_DB_UNLOCK", "1") != "0"
        return cfg


def _default_db_path() -> Path | None:
    from pyrekordbox.config import get_config

    for version in ("rekordbox7", "rekordbox6"):
        path = (get_config(version) or {}).get("db_path")
        if path:
            return Path(path)
    return None


def _default_downloads_dir() -> Path | None:
    home = Path.home()
    for candidate in (
        home / "Library" / "CloudStorage" / "Dropbox" / "New Downloads",
        home / "Dropbox" / "New Downloads",
    ):
        if candidate.is_dir():
            return candidate
    return None


class Library:
    def __init__(self, config: Config | None = None):
        self.config = config or Config.from_env()

    # -- connection -----------------------------------------------------------------

    @property
    def db_path(self) -> Path:
        path = self.config.db_path or _default_db_path()
        if not path or not Path(path).exists():
            raise LibraryError(
                "Couldn't find your Rekordbox library (master.db). Set REKORDBOX_DB_PATH in the "
                "Claude Desktop config, usually ~/Library/Pioneer/rekordbox/master.db on a Mac."
            )
        return Path(path)

    def _open(self) -> Rekordbox6Database:
        try:
            return Rekordbox6Database(path=str(self.db_path), unlock=self.config.unlock)
        except LibraryError:
            raise
        except Exception as exc:  # pyrekordbox raises a variety of errors for locked/unknown DBs
            raise LibraryError(f"Couldn't open the Rekordbox library: {exc}") from exc

    @contextmanager
    def read(self) -> Iterator[Rekordbox6Database]:
        db = self._open()
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def write(self) -> Iterator[tuple[Rekordbox6Database, Path]]:
        """Open for writing: refuses while Rekordbox runs, backs up first, commits on success."""
        if rekordbox_running():
            raise LibraryError(
                "Rekordbox is open. Quit Rekordbox first so changes can be saved safely, then ask again."
            )
        backup = self.backup()
        db = self._open()
        try:
            yield db, backup
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def backup(self) -> Path:
        """Copy master.db (and masterPlaylists6.xml) into a timestamped backup folder."""
        src = self.db_path
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        dest = self.config.backup_dir / stamp
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / src.name)
        xml = src.parent / "masterPlaylists6.xml"
        if xml.exists():
            shutil.copy2(xml, dest / xml.name)
        self._prune_backups()
        return dest

    def _prune_backups(self) -> None:
        root = self.config.backup_dir
        backups = sorted(p for p in root.iterdir() if p.is_dir() and (p / self.db_path.name).exists())
        for old in backups[:-MAX_BACKUPS]:
            shutil.rmtree(old)

    # -- loading --------------------------------------------------------------------

    def _lookups(self, db: Rekordbox6Database) -> dict[str, dict]:
        def names(table, attr="Name"):
            return {str(r.ID): getattr(r, attr) for r in db.query(table)}

        my_tags: dict[str, list[str]] = defaultdict(list)
        tag_names = names(tables.DjmdMyTag)
        for link in db.query(tables.DjmdSongMyTag):
            name = tag_names.get(str(link.MyTagID))
            if name:
                my_tags[str(link.ContentID)].append(name)

        last_played: dict[str, str] = {}
        history_plays: Counter = Counter()
        hist_dates = {str(h.ID): _date(h.DateCreated) for h in db.query(tables.DjmdHistory)}
        for song in db.query(tables.DjmdSongHistory):
            cid = str(song.ContentID)
            day = hist_dates.get(str(song.HistoryID))
            history_plays[cid] += 1
            if day and (cid not in last_played or day > last_played[cid]):
                last_played[cid] = day

        return {
            "artist": names(tables.DjmdArtist),
            "album": names(tables.DjmdAlbum),
            "genre": names(tables.DjmdGenre),
            "label": names(tables.DjmdLabel),
            "key": names(tables.DjmdKey, "ScaleName"),
            "color": names(tables.DjmdColor, "Commnt"),
            "my_tags": my_tags,
            "last_played": last_played,
            "history_plays": history_plays,
        }

    @staticmethod
    def _track(c: tables.DjmdContent, lk: dict[str, dict]) -> dict:
        cid = str(c.ID)
        key = lk["key"].get(str(c.KeyID)) if c.KeyID else None
        length = _as_int(c.Length)
        return {
            "id": cid,
            "title": c.Title or Path(c.FolderPath or "").stem,
            "artist": lk["artist"].get(str(c.ArtistID)) if c.ArtistID else None,
            "remixer": lk["artist"].get(str(c.RemixerID)) if c.RemixerID else None,
            "album": lk["album"].get(str(c.AlbumID)) if c.AlbumID else None,
            "label": lk["label"].get(str(c.LabelID)) if c.LabelID else None,
            "genre": lk["genre"].get(str(c.GenreID)) if c.GenreID else None,
            "bpm": round(_as_int(c.BPM) / 100, 2) or None,
            "key": key,
            "camelot": to_camelot(key),
            "length_sec": length,
            "duration": _fmt_len(length),
            "rating": _stars(c.Rating),
            "color": lk["color"].get(str(c.ColorID)) if c.ColorID else None,
            "comment": c.Commnt or None,
            "my_tags": sorted(lk["my_tags"].get(cid, [])),
            "play_count": max(_as_int(c.DJPlayCount), lk["history_plays"].get(cid, 0)),
            "last_played": lk["last_played"].get(cid),
            "date_added": _date(c.StockDate) or _date(c.DateCreated),
            "release_year": c.ReleaseYear or None,
            "file_type": FILE_TYPE_NAMES.get(_as_int(c.FileType), str(c.FileType)),
            "bitrate": c.BitRate or None,
            "file_path": c.FolderPath,
        }

    def _contents(self, db: Rekordbox6Database):
        return db.query(tables.DjmdContent).filter(
            (tables.DjmdContent.rb_local_deleted == 0) | (tables.DjmdContent.rb_local_deleted.is_(None))
        )

    def _load_tracks(self, db: Rekordbox6Database) -> list[dict]:
        lk = self._lookups(db)
        return [self._track(c, lk) for c in self._contents(db)]

    def all_tracks(self) -> list[dict]:
        with self.read() as db:
            return self._load_tracks(db)

    # -- search ---------------------------------------------------------------------

    def search_tracks(
        self,
        text: str | None = None,
        artist: str | None = None,
        genre: str | None = None,
        bpm_min: float | None = None,
        bpm_max: float | None = None,
        key: str | None = None,
        harmonic_with: str | None = None,
        min_rating: int | None = None,
        my_tag: str | None = None,
        color: str | None = None,
        playlist: str | None = None,
        added_after: str | None = None,
        not_played_since: str | None = None,
        sort_by: str = "title",
        limit: int = 50,
    ) -> dict:
        tracks = self.all_tracks() if not playlist else self.playlist_tracks(playlist)["tracks"]
        return filter_tracks(
            tracks, text=text, artist=artist, genre=genre, bpm_min=bpm_min, bpm_max=bpm_max,
            key=key, harmonic_with=harmonic_with, min_rating=min_rating, my_tag=my_tag,
            color=color, added_after=added_after, not_played_since=not_played_since,
            sort_by=sort_by, limit=limit,
        )

    def get_tracks(self, track_ids: list[str]) -> list[dict]:
        wanted = [str(t) for t in track_ids]
        by_id = {t["id"]: t for t in self.all_tracks()}
        missing = [t for t in wanted if t not in by_id]
        if missing:
            raise LibraryError(f"No tracks with these IDs: {', '.join(missing)}")
        return [by_id[t] for t in wanted]

    def track_details(self, track_id: str) -> dict:
        with self.read() as db:
            lk = self._lookups(db)
            c = self._contents(db).filter(tables.DjmdContent.ID == str(track_id)).one_or_none()
            if c is None:
                raise LibraryError(f"No track with ID {track_id}")
            track = self._track(c, lk)
            cues = db.query(tables.DjmdCue).filter(tables.DjmdCue.ContentID == str(track_id)).all()
            track["hot_cues"] = sum(1 for q in cues if _as_int(q.Kind) > 0)
            track["memory_cues"] = sum(1 for q in cues if _as_int(q.Kind) == 0)
            playlists = {str(p.ID): p.Name for p in db.query(tables.DjmdPlaylist)}
            track["in_playlists"] = sorted(
                {
                    playlists.get(str(s.PlaylistID), "?")
                    for s in db.query(tables.DjmdSongPlaylist).filter(
                        tables.DjmdSongPlaylist.ContentID == str(track_id)
                    )
                }
            )
            track["file_exists"] = bool(c.FolderPath) and Path(c.FolderPath).exists()
            return track

    def suggest_next(self, track_id: str, bpm_range_pct: float = 6.0, limit: int = 15) -> dict:
        tracks = self.all_tracks()
        current = next((t for t in tracks if t["id"] == str(track_id)), None)
        if current is None:
            raise LibraryError(f"No track with ID {track_id}")
        if not current["bpm"]:
            raise LibraryError("That track has no BPM yet. Analyze it in Rekordbox first.")
        lo = current["bpm"] * (1 - bpm_range_pct / 100)
        hi = current["bpm"] * (1 + bpm_range_pct / 100)
        result = filter_tracks(
            [t for t in tracks if t["id"] != current["id"]],
            bpm_min=lo, bpm_max=hi, harmonic_with=current["key"], sort_by="rating", limit=limit,
        )
        result["current"] = current
        return result

    # -- playlists ------------------------------------------------------------------

    def list_playlists(self) -> list[dict]:
        with self.read() as db:
            rows = list(db.query(tables.DjmdPlaylist))
            counts = Counter(str(s.PlaylistID) for s in db.query(tables.DjmdSongPlaylist))
            by_parent: dict[str, list] = defaultdict(list)
            for p in rows:
                by_parent[str(p.ParentID)].append(p)

            def build(parent: str, prefix: str) -> list[dict]:
                out = []
                for p in sorted(by_parent.get(parent, []), key=lambda r: _as_int(r.Seq)):
                    path = f"{prefix}{p.Name}"
                    kind = PLAYLIST_KIND.get(_as_int(p.Attribute), "playlist")
                    entry = {"id": str(p.ID), "name": p.Name, "path": path, "type": kind}
                    if kind == "playlist":
                        entry["track_count"] = counts.get(str(p.ID), 0)
                    out.append(entry)
                    if kind == "folder":
                        out.extend(build(str(p.ID), path + "/"))
                return out

            return build("root", "")

    def _resolve_playlist(self, db: Rekordbox6Database, playlist: str) -> tables.DjmdPlaylist:
        rows = list(db.query(tables.DjmdPlaylist))
        for p in rows:
            if str(p.ID) == str(playlist):
                return p
        name = playlist.strip().lower().split("/")[-1]
        matches = [p for p in rows if (p.Name or "").lower() == name]
        if not matches:
            raise LibraryError(f"No playlist called '{playlist}'. Use list_playlists to see them.")
        if len(matches) > 1:
            ids = ", ".join(f"{m.Name} (id {m.ID})" for m in matches)
            raise LibraryError(f"Several playlists are called '{playlist}': {ids}. Use the id instead.")
        return matches[0]

    def playlist_tracks(self, playlist: str) -> dict:
        with self.read() as db:
            pl = self._resolve_playlist(db, playlist)
            lk = self._lookups(db)
            kind = PLAYLIST_KIND.get(_as_int(pl.Attribute), "playlist")
            if kind == "folder":
                raise LibraryError(f"'{pl.Name}' is a folder, not a playlist.")
            if kind == "smart playlist":
                contents = list(db.get_playlist_contents(pl))
            else:
                ids = [
                    str(s.ContentID)
                    for s in db.query(tables.DjmdSongPlaylist)
                    .filter(tables.DjmdSongPlaylist.PlaylistID == str(pl.ID))
                    .order_by(tables.DjmdSongPlaylist.TrackNo)
                ]
                by_id = {
                    str(c.ID): c
                    for c in db.query(tables.DjmdContent).filter(tables.DjmdContent.ID.in_(ids))
                }
                contents = [by_id[i] for i in ids if i in by_id]
            tracks = [self._track(c, lk) for c in contents]
            return {
                "id": str(pl.ID),
                "name": pl.Name,
                "type": kind,
                "track_count": len(tracks),
                "total_minutes": round(sum(t["length_sec"] for t in tracks) / 60, 1),
                "tracks": tracks,
            }

    def create_playlist(self, name: str, track_ids: list[str], folder: str | None = None) -> dict:
        tracks = self.get_tracks(track_ids) if track_ids else []
        with self.write() as (db, backup):
            parent = None
            if folder:
                try:
                    parent = self._resolve_playlist(db, folder)
                except LibraryError:
                    parent = db.create_playlist_folder(folder)
                if _as_int(parent.Attribute) != 1:
                    raise LibraryError(f"'{folder}' is a playlist, not a folder.")
            pl = db.create_playlist(name, parent=parent)
            for t in tracks:
                db.add_to_playlist(pl, t["id"])
            result = {"id": str(pl.ID), "name": name, "folder": folder, "tracks_added": len(tracks)}
        result["backup"] = str(backup)
        return result

    def add_to_playlist(self, playlist: str, track_ids: list[str], skip_existing: bool = True) -> dict:
        self.get_tracks(track_ids)  # validates IDs
        with self.write() as (db, backup):
            pl = self._resolve_playlist(db, playlist)
            if _as_int(pl.Attribute) != 0:
                raise LibraryError(f"'{pl.Name}' isn't a regular playlist, so tracks can't be added to it.")
            existing = {
                str(s.ContentID)
                for s in db.query(tables.DjmdSongPlaylist).filter(tables.DjmdSongPlaylist.PlaylistID == str(pl.ID))
            }
            added, skipped = 0, 0
            for tid in track_ids:
                if skip_existing and str(tid) in existing:
                    skipped += 1
                    continue
                db.add_to_playlist(pl, str(tid))
                existing.add(str(tid))
                added += 1
            result = {"playlist": pl.Name, "added": added, "skipped_already_in_playlist": skipped}
        result["backup"] = str(backup)
        return result

    # -- editing --------------------------------------------------------------------

    def list_my_tags(self) -> list[dict]:
        with self.read() as db:
            rows = list(db.query(tables.DjmdMyTag))
            names = {str(r.ID): r.Name for r in rows}
            counts = Counter(str(s.MyTagID) for s in db.query(tables.DjmdSongMyTag))
            return [
                {"category": names.get(str(r.ParentID)), "tag": r.Name, "track_count": counts.get(str(r.ID), 0)}
                for r in sorted(rows, key=lambda r: (str(r.ParentID), _as_int(r.Seq)))
                if str(r.ParentID) != "root"
            ]

    def list_colors(self) -> list[str]:
        with self.read() as db:
            return [c.Commnt for c in db.query(tables.DjmdColor).order_by(tables.DjmdColor.SortKey)]

    def update_tracks(
        self,
        track_ids: list[str],
        genre: str | None = None,
        comment: str | None = None,
        append_comment: str | None = None,
        rating: int | None = None,
        color: str | None = None,
        add_my_tags: list[str] | None = None,
        remove_my_tags: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict:
        if rating is not None and not 0 <= rating <= 5:
            raise LibraryError("Rating must be 0-5 stars.")
        before = self.get_tracks(track_ids)
        changes = []
        for t in before:
            change = {"id": t["id"], "track": f"{t['artist'] or '?'} - {t['title']}"}
            if genre is not None and genre != t["genre"]:
                change["genre"] = [t["genre"], genre]
            if comment is not None or append_comment:
                new = comment if comment is not None else (t["comment"] or "")
                if append_comment and append_comment not in new:
                    new = f"{new} {append_comment}".strip()
                if new != (t["comment"] or ""):
                    change["comment"] = [t["comment"], new]
            if rating is not None and rating != t["rating"]:
                change["rating"] = [t["rating"], rating]
            if color is not None and (color or None) != t["color"]:
                change["color"] = [t["color"], color or None]
            add = [m for m in (add_my_tags or []) if m not in t["my_tags"]]
            rem = [m for m in (remove_my_tags or []) if m in t["my_tags"]]
            if add:
                change["add_my_tags"] = add
            if rem:
                change["remove_my_tags"] = rem
            if len(change) > 2:
                changes.append(change)

        summary = {"tracks_checked": len(before), "tracks_changing": len(changes), "changes": changes}
        if dry_run or not changes:
            summary["applied"] = False
            return summary

        with self.write() as (db, backup):
            genre_id = self._genre_id(db, genre) if genre else None
            color_id = self._color_id(db, color) if color else None
            tag_ids = self._my_tag_ids(db, (add_my_tags or []) + (remove_my_tags or []))
            for change in changes:
                c = db.get_content(ID=change["id"])
                if "genre" in change:
                    c.GenreID = genre_id
                if "comment" in change:
                    c.Commnt = change["comment"][1]
                if "rating" in change:
                    c.Rating = rating
                if "color" in change:
                    c.ColorID = color_id
                for tag in change.get("add_my_tags", []):
                    self._add_my_tag(db, c.ID, tag_ids[tag])
                for tag in change.get("remove_my_tags", []):
                    for link in db.query(tables.DjmdSongMyTag).filter_by(ContentID=str(c.ID), MyTagID=tag_ids[tag]):
                        db.delete(link)
        summary["applied"] = True
        summary["backup"] = str(backup)
        return summary

    @staticmethod
    def _genre_id(db: Rekordbox6Database, name: str) -> str:
        existing = db.query(tables.DjmdGenre).filter(tables.DjmdGenre.Name == name).first()
        return str((existing or db.add_genre(name)).ID)

    @staticmethod
    def _color_id(db: Rekordbox6Database, name: str) -> str:
        for c in db.query(tables.DjmdColor):
            if (c.Commnt or "").lower() == name.lower():
                return str(c.ID)
        options = ", ".join(c.Commnt for c in db.query(tables.DjmdColor))
        raise LibraryError(f"Unknown color '{name}'. Options: {options}")

    @staticmethod
    def _my_tag_ids(db: Rekordbox6Database, names: list[str]) -> dict[str, str]:
        rows = [r for r in db.query(tables.DjmdMyTag) if str(r.ParentID) != "root"]
        by_name = {(r.Name or "").lower(): str(r.ID) for r in rows}
        missing = [n for n in names if n.lower() not in by_name]
        if missing:
            raise LibraryError(
                f"These My Tags don't exist yet: {', '.join(missing)}. Create them in Rekordbox "
                f"(My Tag panel) first. Existing tags: {', '.join(sorted(r.Name for r in rows))}"
            )
        return {n: by_name[n.lower()] for n in names}

    @staticmethod
    def _add_my_tag(db: Rekordbox6Database, content_id: Any, tag_id: str) -> None:
        from uuid import uuid4

        track_no = db.query(tables.DjmdSongMyTag).filter_by(MyTagID=tag_id).count() + 1
        now = dt.datetime.now()
        link = tables.DjmdSongMyTag.create(
            ID=str(uuid4()), UUID=str(uuid4()), MyTagID=tag_id, ContentID=str(content_id),
            TrackNo=track_no, created_at=now, updated_at=now,
        )
        db.add(link)

    # -- cleanup --------------------------------------------------------------------

    def find_duplicates(self, limit: int = 50) -> dict:
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for t in self.all_tracks():
            title = normalize_title(t["title"])
            if title:
                groups[(normalize_artist(t["artist"]), title)].append(t)
        dupes = []
        for tracks in groups.values():
            if len(tracks) < 2:
                continue
            keep = max(
                tracks,
                key=lambda t: (t["file_type"] in LOSSLESS_TYPES, t["bitrate"] or 0, t["play_count"], t["rating"]),
            )
            lengths = [t["length_sec"] for t in tracks if t["length_sec"]]
            dupes.append({
                "artist": tracks[0]["artist"],
                "title": tracks[0]["title"],
                "copies": [_brief(t, "file_type", "bitrate", "length_sec", "play_count", "file_path") for t in tracks],
                "suggest_keep_id": keep["id"],
                "note": "lengths differ by >5s, may be different versions"
                if lengths and max(lengths) - min(lengths) > 5 else None,
            })
        dupes.sort(key=lambda d: (d["artist"] or "", d["title"] or ""))
        return {"duplicate_groups": len(dupes), "groups": dupes[:limit]}

    def find_missing_files(self, limit: int = 100) -> dict:
        missing = [t for t in self.all_tracks() if t["file_path"] and not Path(t["file_path"]).exists()]
        volumes = Counter(
            "/".join(Path(t["file_path"]).parts[:3]) for t in missing if t["file_path"].startswith("/Volumes/")
        )
        return {
            "missing_count": len(missing),
            "on_external_drives": dict(volumes),
            "hint": "Tracks on /Volumes/... may just be on a drive that isn't plugged in." if volumes else None,
            "tracks": [_brief(t, "file_path") for t in missing[:limit]],
        }

    def find_incomplete(self, fields: list[str] | None = None, limit: int = 100) -> dict:
        fields = fields or ["genre", "key", "bpm", "artist", "rating", "my_tags"]
        empty = {f: [] for f in fields}
        for t in self.all_tracks():
            for f in fields:
                if not t.get(f):
                    empty[f].append(t)
        return {
            "counts": {f: len(v) for f, v in empty.items()},
            "examples": {f: [_brief(t) for t in v[:limit]] for f, v in empty.items()},
            "hint": "Missing BPM/key usually means the track hasn't been analyzed in Rekordbox yet.",
        }

    def find_unplayed(self, days: int = 365, limit: int = 100) -> dict:
        cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        stale = [
            t for t in self.all_tracks()
            if (t["last_played"] or "") < cutoff and (t["date_added"] or "") < cutoff
        ]
        stale.sort(key=lambda t: (t["last_played"] or "", t["date_added"] or ""))
        never = sum(1 for t in stale if not t["play_count"])
        return {
            "count": len(stale),
            "never_played": never,
            "note": "Last-played dates come from Rekordbox's History; tracks played before the "
            "history was cleared show play_count > 0 with no last_played date.",
            "tracks": [_brief(t, "last_played", "date_added", "play_count", "genre") for t in stale[:limit]],
        }

    def find_without_cues(self, limit: int = 100) -> dict:
        with self.read() as db:
            hot = Counter(
                str(q.ContentID) for q in db.query(tables.DjmdCue) if _as_int(q.Kind) > 0
            )
            tracks = self._load_tracks(db)
        none = [t for t in tracks if not hot.get(t["id"])]
        return {"count": len(none), "tracks": [_brief(t, "genre", "date_added") for t in none[:limit]]}

    # -- stats ----------------------------------------------------------------------

    def overview(self) -> dict:
        tracks = self.all_tracks()
        total = sum(t["length_sec"] for t in tracks)
        bpm_buckets = Counter(f"{int(t['bpm'] // 5 * 5)}-{int(t['bpm'] // 5 * 5) + 4}" for t in tracks if t["bpm"])
        months = Counter((t["date_added"] or "")[:7] for t in tracks if t["date_added"])
        recent_months = dict(sorted(months.items())[-12:])
        return {
            "tracks": len(tracks),
            "total_hours": round(total / 3600, 1),
            "top_genres": Counter(t["genre"] or "(none)" for t in tracks).most_common(15),
            "top_artists": Counter(t["artist"] for t in tracks if t["artist"]).most_common(15),
            "bpm_ranges": dict(sorted(bpm_buckets.items(), key=lambda kv: int(kv[0].split("-")[0]))),
            "keys": dict(Counter(t["camelot"] or "(unknown)" for t in tracks).most_common()),
            "file_types": dict(Counter(t["file_type"] for t in tracks)),
            "added_per_month": recent_months,
            "not_analyzed": sum(1 for t in tracks if not t["bpm"] or not t["key"]),
            "unrated": sum(1 for t in tracks if not t["rating"]),
            "never_played": sum(1 for t in tracks if not t["play_count"]),
            "playlists": len(self.list_playlists()),
        }

    def play_history(self, days: int = 90, include_tracks: bool = True, limit: int = 20) -> dict:
        cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        with self.read() as db:
            lk = self._lookups(db)
            sessions = [
                h for h in db.query(tables.DjmdHistory)
                if _as_int(h.Attribute) == 0 and (_date(h.DateCreated) or "") >= cutoff
            ]
            sessions.sort(key=lambda h: _date(h.DateCreated) or "", reverse=True)
            out = []
            for h in sessions[:limit]:
                songs = (
                    db.query(tables.DjmdSongHistory)
                    .filter(tables.DjmdSongHistory.HistoryID == str(h.ID))
                    .order_by(tables.DjmdSongHistory.TrackNo)
                    .all()
                )
                entry = {"name": h.Name, "date": _date(h.DateCreated), "track_count": len(songs)}
                if include_tracks:
                    entry["tracks"] = [
                        _brief(self._track(s.Content, lk)) for s in songs if s.Content is not None
                    ]
                out.append(entry)
            return {"sessions": len(sessions), "history": out}

    def most_played(self, limit: int = 25, days: int | None = None) -> dict:
        with self.read() as db:
            lk = self._lookups(db)
            if days:
                cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
                ok = {str(h.ID) for h in db.query(tables.DjmdHistory) if (_date(h.DateCreated) or "") >= cutoff}
                plays = Counter(
                    str(s.ContentID) for s in db.query(tables.DjmdSongHistory) if str(s.HistoryID) in ok
                )
                tracks = {str(c.ID): self._track(c, lk) for c in self._contents(db)}
                top = [
                    dict(_brief(tracks[cid], "genre", "last_played"), plays=n)
                    for cid, n in plays.most_common(limit) if cid in tracks
                ]
            else:
                tracks = [self._track(c, lk) for c in self._contents(db)]
                tracks.sort(key=lambda t: t["play_count"], reverse=True)
                top = [
                    dict(_brief(t, "genre", "last_played"), plays=t["play_count"])
                    for t in tracks[:limit] if t["play_count"]
                ]
            return {"window_days": days, "tracks": top}

    # -- downloads, matching & discovery -------------------------------------------

    def downloads_dir(self, folder: str | None = None) -> Path:
        path = Path(folder).expanduser() if folder else (self.config.downloads_dir or _default_downloads_dir())
        if not path or not path.is_dir():
            raise LibraryError(
                "Couldn't find the downloads folder. Pass a folder path, or set "
                "REKORDBOX_MCP_DOWNLOADS_DIR (e.g. ~/Library/CloudStorage/Dropbox/New Downloads)."
            )
        return path

    def scan_downloads(self, folder: str | None = None, limit: int = 200) -> dict:
        root = self.downloads_dir(folder)
        tracks = self.all_tracks()
        known_paths = {_nfc(t["file_path"]) for t in tracks if t["file_path"]}
        new, already = [], 0
        for path in sorted(root.rglob("*")):
            if path.suffix.lower() not in AUDIO_EXTENSIONS or path.name.startswith("."):
                continue
            if _nfc(str(path)) in known_paths:
                already += 1
                continue
            info = read_file_tags(path)
            matches = best_matches(info["artist"] or "", info["title"], tracks, min_score=0.85, limit=1)
            if matches:
                m = matches[0][1]
                info["possible_duplicate_of"] = {"id": m["id"], "track": f"{m['artist']} - {m['title']}",
                                                 "file_path": m["file_path"]}
            info["importable"] = path.suffix.lower() in IMPORTABLE_EXTENSIONS
            new.append(info)
        return {
            "folder": str(root),
            "new_files": len(new),
            "already_in_library": already,
            "files": new[:limit],
        }

    def import_files(self, file_paths: list[str], playlist: str | None = None) -> dict:
        paths = [Path(p).expanduser() for p in file_paths]
        problems = [str(p) for p in paths if not p.is_file()]
        if problems:
            raise LibraryError(f"These files don't exist: {', '.join(problems)}")
        unsupported = [str(p) for p in paths if p.suffix.lower() not in IMPORTABLE_EXTENSIONS]
        if unsupported:
            raise LibraryError(
                "These can't be added directly (drag them into Rekordbox instead, or rename .aif to "
                f".aiff): {', '.join(unsupported)}"
            )
        with self.write() as (db, backup):
            known = {_nfc(c.FolderPath or "") for c in db.query(tables.DjmdContent)}
            pl = self._resolve_or_create_playlist(db, playlist) if playlist else None
            added, skipped = [], []
            for p in paths:
                if _nfc(str(p)) in known:
                    skipped.append(str(p))
                    continue
                info = read_file_tags(p)
                kwargs: dict[str, Any] = {"Title": info["title"]}
                if info["artist"]:
                    kwargs["ArtistID"] = str(self._artist(db, info["artist"]).ID)
                if info["genre"]:
                    kwargs["GenreID"] = self._genre_id(db, info["genre"])
                content = db.add_content(str(p), **kwargs)
                if pl is not None:
                    db.add_to_playlist(pl, content)
                known.add(_nfc(str(p)))
                added.append({"id": str(content.ID), "file": p.name, "artist": info["artist"], "title": info["title"]})
            result = {"added": added, "skipped_already_in_library": skipped, "playlist": playlist}
        result["backup"] = str(backup)
        result["next_step"] = (
            "Open Rekordbox, select the new tracks and choose Analyze Track so they get BPM, key and waveforms."
        )
        return result

    def _resolve_or_create_playlist(self, db: Rekordbox6Database, name: str) -> tables.DjmdPlaylist:
        try:
            return self._resolve_playlist(db, name)
        except LibraryError:
            return db.create_playlist(name)

    @staticmethod
    def _artist(db: Rekordbox6Database, name: str) -> tables.DjmdArtist:
        existing = db.query(tables.DjmdArtist).filter(tables.DjmdArtist.Name == name).first()
        return existing or db.add_artist(name)

    def match_tracks(self, wanted: list[str], min_score: float = 0.8) -> dict:
        """Check a tracklist (e.g. a Spotify playlist) against the library."""
        tracks = self.all_tracks()
        found, missing = [], []
        for line in wanted:
            artist, title = split_artist_title(line)
            if not title:
                continue
            matches = best_matches(artist, title, tracks, min_score=min_score, limit=1)
            if matches:
                score, t = matches[0]
                found.append({"wanted": line, "match": _brief(t, "bpm", "key"), "confidence": score})
            else:
                missing.append({"wanted": line, "where_to_get_it": discovery.store_links(artist, title)})
        return {
            "checked": len(found) + len(missing),
            "in_library": len(found),
            "missing": len(missing),
            "found": found,
            "missing_tracks": missing,
        }

    def discovery_sources(self, artists: int = 10, genres: int = 5, based_on: str = "plays") -> dict:
        tracks = self.all_tracks()
        if based_on == "recent":
            tracks = sorted(tracks, key=lambda t: t["date_added"] or "", reverse=True)[:300]
            weight = {t["id"]: 1 for t in tracks}
        else:
            weight = {t["id"]: t["play_count"] or 0 for t in tracks}
        artist_score: Counter = Counter()
        genre_score: Counter = Counter()
        for t in tracks:
            w = weight.get(t["id"], 0)
            if w and t["artist"]:
                artist_score[t["artist"]] += w
            if w and t["genre"]:
                genre_score[t["genre"]] += w
        return {
            "based_on": based_on,
            "artists": [{"artist": a, "links": discovery.artist_links(a)} for a, _ in artist_score.most_common(artists)],
            "genres": [{"genre": g, "links": discovery.genre_links(g)} for g, _ in genre_score.most_common(genres)],
        }


def _brief(t: dict, *extra: str) -> dict:
    out = {"id": t["id"], "artist": t["artist"], "title": t["title"], "bpm": t["bpm"], "key": t["camelot"] or t["key"]}
    for f in extra:
        out[f] = t.get(f)
    return out


def read_file_tags(path: Path) -> dict:
    """Artist/title/genre from the file's tags, falling back to "Artist - Title" filenames."""
    artist, title = split_artist_title(path.stem)
    info = {"file_path": str(path), "file": path.name, "artist": artist or None, "title": title,
            "genre": None, "bpm": None, "size_mb": round(path.stat().st_size / 1e6, 1)}
    try:
        import mutagen

        tags = mutagen.File(path, easy=True)
    except Exception:
        tags = None
    if tags:
        def first(key: str) -> str | None:
            vals = tags.get(key) if hasattr(tags, "get") else None
            return str(vals[0]).strip() if vals else None
        info["artist"] = first("artist") or info["artist"]
        info["title"] = first("title") or info["title"]
        info["genre"] = first("genre")
        info["bpm"] = first("bpm")
    return info


def filter_tracks(
    tracks: list[dict],
    text: str | None = None,
    artist: str | None = None,
    genre: str | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    key: str | None = None,
    harmonic_with: str | None = None,
    min_rating: int | None = None,
    my_tag: str | None = None,
    color: str | None = None,
    added_after: str | None = None,
    not_played_since: str | None = None,
    sort_by: str = "title",
    limit: int = 50,
) -> dict:
    key_codes = {to_camelot(key)} if key else None
    if key and key_codes == {None}:
        raise LibraryError(f"Couldn't understand the key '{key}'. Use Camelot (8A) or classic (Am) notation.")
    harmonic = set(compatible_keys(harmonic_with)) if harmonic_with else None
    words = normalize_title(text).split() if text else []

    def keep(t: dict) -> bool:
        if words:
            hay = normalize_title(" ".join(str(t.get(f) or "") for f in
                                           ("artist", "title", "remixer", "album", "label", "genre", "comment")))
            if not all(w in hay.split() or w in hay for w in words):
                return False
        if artist and normalize_artist(artist) not in normalize_artist(f"{t['artist'] or ''} {t['remixer'] or ''}"):
            return False
        if genre and genre.lower() not in (t["genre"] or "").lower():
            return False
        if bpm_min is not None and not (t["bpm"] and t["bpm"] >= bpm_min):
            return False
        if bpm_max is not None and not (t["bpm"] and t["bpm"] <= bpm_max):
            return False
        if key_codes and t["camelot"] not in key_codes:
            return False
        if harmonic is not None and t["camelot"] not in harmonic:
            return False
        if min_rating and t["rating"] < min_rating:
            return False
        if my_tag and my_tag.lower() not in [m.lower() for m in t["my_tags"]]:
            return False
        if color and (t["color"] or "").lower() != color.lower():
            return False
        if added_after and (t["date_added"] or "") < added_after:
            return False
        if not_played_since and (t["last_played"] or "") >= not_played_since:
            return False
        return True

    hits = [t for t in tracks if keep(t)]
    sorters = {
        "title": lambda t: (t["title"] or "").lower(),
        "artist": lambda t: ((t["artist"] or "").lower(), (t["title"] or "").lower()),
        "bpm": lambda t: t["bpm"] or 0,
        "rating": lambda t: (-t["rating"], -(t["play_count"] or 0)),
        "play_count": lambda t: -(t["play_count"] or 0),
        "date_added": lambda t: t["date_added"] or "",
        "key": lambda t: (int((t["camelot"] or "99Z")[:-1]), (t["camelot"] or "Z")[-1]),
    }
    if sort_by not in sorters and sort_by != "newest":
        raise LibraryError(f"sort_by must be one of: {', '.join([*sorters, 'newest'])}")
    if sort_by == "newest":
        hits.sort(key=lambda t: t["date_added"] or "", reverse=True)
    else:
        hits.sort(key=sorters[sort_by])
    return {"total_matches": len(hits), "returned": min(len(hits), limit), "tracks": hits[:limit]}
