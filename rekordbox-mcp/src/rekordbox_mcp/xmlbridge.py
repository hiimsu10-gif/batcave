"""Playlists delivered through a rekordbox.xml file, which Rekordbox can load while it's running."""

from __future__ import annotations

import os
from pathlib import Path

from pyrekordbox.rbxml import RekordboxXml, decode_path

ROOT_FOLDER = "Claude"

HOW_TO_LOAD = (
    "Rekordbox is open, so the playlist '{name}' was written to {path} instead of straight into "
    "the library. In Rekordbox: open the 'rekordbox xml' section at the bottom of the left "
    "sidebar, click its refresh icon, open the '" + ROOT_FOLDER + "' folder, then right-click "
    "'{name}' and choose Import Playlist. First time only: Preferences > Advanced > Database > "
    "rekordbox xml > Imported Library, pick that file; and Preferences > View > Layout, tick "
    "'rekordbox xml' so it shows in the sidebar."
)


def _key(path: str) -> str:
    # pyrekordbox's encode/decode assume Windows drive paths ("C:/..."). On a Mac we pass paths
    # without the leading "/" so Locations come out as Rekordbox writes them:
    # file://localhost/Users/...
    return os.path.normpath(decode_path(path) if path.startswith("file:") else path).lstrip("/")


def _child(node, name: str):
    for sub in node.get_playlists():
        if sub.name == name:
            return sub
    return None


def add_playlist(xml_path: Path, name: str, tracks: list[dict], folder: str | None = None) -> Path:
    """Add (or replace) a playlist under Claude/<folder>/ in the XML file.

    ``tracks`` are track dicts with at least ``file_path``; ``title``, ``artist`` and
    ``genre`` are used for tracks Rekordbox doesn't know yet.
    """
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml = RekordboxXml(xml_path) if xml_path.exists() else RekordboxXml(
        name="rekordbox-mcp", version="0.1", company="Claude"
    )
    ids = {_key(t["Location"]): int(t["TrackID"]) for t in xml.get_tracks()}

    parent = xml.root_playlist_folder
    for part in [ROOT_FOLDER, *([folder] if folder else [])]:
        parent = _child(parent, part) or parent.add_playlist_folder(part)
    if _child(parent, name) is not None:
        parent.remove_playlist(name)
    playlist = parent.add_playlist(name)

    for t in tracks:
        key = _key(t["file_path"])
        if key not in ids:
            attrs = {k: v for k, v in (("Name", t.get("title")), ("Artist", t.get("artist")),
                                       ("Genre", t.get("genre"))) if v}
            # pyrekordbox doesn't track the highest existing TrackID after re-reading a file
            attrs["TrackID"] = max(ids.values(), default=0) + 1
            ids[key] = int(xml.add_track(key, **attrs)["TrackID"])
        playlist.add_track(ids[key])

    xml.save(xml_path)
    return xml_path
