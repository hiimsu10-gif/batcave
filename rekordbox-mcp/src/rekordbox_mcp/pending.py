"""Edits queued while Rekordbox is open, applied once it's closed."""

from __future__ import annotations

import datetime as dt
import json
import threading
import uuid
from pathlib import Path

MAX_HISTORY = 50


class PendingQueue:
    """A small JSON file: {"pending": [...], "history": [...]}."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        return {"pending": data.get("pending", []), "history": data.get("history", [])}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path)

    def add(self, kind: str, args: dict, tracks_changing: int) -> dict:
        item = {
            "id": uuid.uuid4().hex[:8],
            "kind": kind,
            "queued_at": dt.datetime.now().isoformat(timespec="seconds"),
            "tracks_changing": tracks_changing,
            "args": args,
        }
        with self._lock:
            data = self._load()
            data["pending"].append(item)
            self._save(data)
        return {"id": item["id"], "queued_at": item["queued_at"], "position": len(data["pending"])}

    def items(self) -> list[dict]:
        with self._lock:
            return self._load()["pending"]

    def cancel(self, item_id: str | None = None) -> int:
        with self._lock:
            data = self._load()
            before = len(data["pending"])
            data["pending"] = [] if item_id is None else [i for i in data["pending"] if i["id"] != item_id]
            self._save(data)
            return before - len(data["pending"])

    def finish(self, ids: list[str], results: list[dict], backup: str) -> None:
        now = dt.datetime.now().isoformat(timespec="seconds")
        with self._lock:
            data = self._load()
            done = set(ids)
            data["pending"] = [i for i in data["pending"] if i["id"] not in done]
            data["history"] = (data["history"] + [dict(r, finished_at=now, backup=backup) for r in results])[
                -MAX_HISTORY:
            ]
            self._save(data)

    def history(self, limit: int = 10) -> list[dict]:
        with self._lock:
            return self._load()["history"][-limit:]
