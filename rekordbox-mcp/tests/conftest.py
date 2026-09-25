"""A small, unencrypted Rekordbox-shaped library for tests."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from pyrekordbox.db6 import tables

from rekordbox_mcp import library as library_mod
from rekordbox_mcp.library import Config, Library

def _row(table, **values):
    return table(**{k: v for k, v in values.items() if v is not None})


KEYS = {"1": "Am", "2": "Em", "3": "C", "4": "Fm", "5": "Bm", "6": "8A"}
COLORS = ["Pink", "Red", "Orange", "Yellow", "Green", "Aqua", "Blue", "Purple"]

TRACKS = [
    # id, title, artist, genre, bpm, key id, length, rating, plays, added, audio file exists
    ("101", "Sunrise", "Alpha", "House", 122, "1", 360, 5, 10, "2024-01-10", True),
    ("102", "Moonrise", "Beta", "House", 123, "2", 400, 4, 3, "2024-02-10", True),
    ("103", "Night Drive", "Gamma", "Techno", 130, "4", 420, 3, 0, "2023-01-01", True),
    ("104", "Sunrise (Original Mix)", "Alpha", "House", 122, "1", 361, 2, 1, "2024-03-01", True),
    ("105", "Deep Blue", "Delta", "Deep House", 120, "3", 380, 0, 0, "2022-05-05", False),
    ("106", "Warehouse", "Gamma", "Techno", 128, "5", 390, 4, 7, "2024-04-04", True),
    ("107", "No Key Yet", "Epsilon", None, 0, None, 300, 0, 0, (dt.date.today() - dt.timedelta(days=5)).isoformat(), True),
]


@pytest.fixture()
def rb(tmp_path: Path, monkeypatch) -> Library:
    music = tmp_path / "Music"
    music.mkdir()
    db_path = tmp_path / "rekordbox" / "master.db"
    db_path.parent.mkdir()
    engine = create_engine(f"sqlite:///{db_path}")
    # The real master.db allows NULL in almost every column; pyrekordbox's models don't say so.
    for table in tables.Base.metadata.tables.values():
        for col in table.columns:
            if not col.primary_key:
                col.nullable = True
    tables.Base.metadata.create_all(engine)
    now = dt.datetime(2025, 1, 1)
    with Session(engine) as s:
        s.add(_row(tables.AgentRegistry, registry_id="localUpdateCount", int_1=100, date_1=now, date_2=now,
                                  created_at=now, updated_at=now))
        s.add(_row(tables.DjmdDevice, ID="1", MasterDBID="1", Name="mac", created_at=now, updated_at=now))
        s.add(_row(tables.DjmdMenuItems, ID="1", Class=1, Name="TRACK", rb_local_usn=1, created_at=now, updated_at=now))
        for kid, name in KEYS.items():
            s.add(_row(tables.DjmdKey, ID=kid, ScaleName=name, Seq=int(kid), created_at=now, updated_at=now))
        for i, name in enumerate(COLORS, 1):
            s.add(_row(tables.DjmdColor, ID=str(i), Commnt=name, SortKey=i, created_at=now, updated_at=now))
        artists, genres = {}, {}
        for tid, title, artist, genre, bpm, key, length, rating, plays, added, exists in TRACKS:
            if artist not in artists:
                artists[artist] = str(900 + len(artists))
                s.add(_row(tables.DjmdArtist, ID=artists[artist], Name=artist, created_at=now, updated_at=now))
            if genre and genre not in genres:
                genres[genre] = str(800 + len(genres))
                s.add(_row(tables.DjmdGenre, ID=genres[genre], Name=genre, created_at=now, updated_at=now))
            path = music / f"{artist} - {title}.mp3"
            if exists:
                path.write_bytes(b"\0" * 10)
            s.add(_row(tables.DjmdContent, 
                ID=tid, Title=title, ArtistID=artists[artist], GenreID=genres.get(genre), BPM=bpm * 100,
                KeyID=key, Length=length, Rating=rating, DJPlayCount=str(plays), StockDate=added,
                FolderPath=str(path), FileType=1, BitRate=320, rb_local_deleted=0,
                created_at=now, updated_at=now,
            ))
        s.add(_row(tables.DjmdCue, ID="c1", ContentID="101", Kind=1, created_at=now, updated_at=now))
        s.add(_row(tables.DjmdCue, ID="c2", ContentID="102", Kind=0, created_at=now, updated_at=now))
        # playlists
        s.add(_row(tables.DjmdPlaylist, ID="10", Name="Sets", ParentID="root", Attribute=1, Seq=1,
                                  created_at=now, updated_at=now))
        s.add(_row(tables.DjmdPlaylist, ID="11", Name="Warmup", ParentID="10", Attribute=0, Seq=1,
                                  created_at=now, updated_at=now))
        for n, cid in enumerate(["102", "101"], 1):
            s.add(_row(tables.DjmdSongPlaylist, ID=f"sp{n}", PlaylistID="11", ContentID=cid, TrackNo=n,
                                          created_at=now, updated_at=now))
        # my tags
        s.add(_row(tables.DjmdMyTag, ID="20", Name="Mood", ParentID="root", Attribute=1, Seq=1,
                               created_at=now, updated_at=now))
        s.add(_row(tables.DjmdMyTag, ID="21", Name="Dark", ParentID="20", Attribute=0, Seq=1,
                               created_at=now, updated_at=now))
        s.add(_row(tables.DjmdMyTag, ID="22", Name="Uplifting", ParentID="20", Attribute=0, Seq=2,
                               created_at=now, updated_at=now))
        s.add(_row(tables.DjmdSongMyTag, ID="st1", MyTagID="21", ContentID="103", TrackNo=1,
                                   created_at=now, updated_at=now))
        # history
        recent = (dt.date.today() - dt.timedelta(days=10)).isoformat()
        s.add(_row(tables.DjmdHistory, ID="30", Name=recent, Attribute=0, ParentID="root", DateCreated=recent,
                                 created_at=now, updated_at=now))
        s.add(_row(tables.DjmdHistory, ID="31", Name="2023-06-01", Attribute=0, ParentID="root",
                                 DateCreated="2023-06-01", created_at=now, updated_at=now))
        s.add(_row(tables.DjmdSongHistory, ID="h1", HistoryID="30", ContentID="101", TrackNo=1,
                                     created_at=now, updated_at=now))
        s.add(_row(tables.DjmdSongHistory, ID="h2", HistoryID="30", ContentID="106", TrackNo=2,
                                     created_at=now, updated_at=now))
        s.add(_row(tables.DjmdSongHistory, ID="h3", HistoryID="31", ContentID="102", TrackNo=1,
                                     created_at=now, updated_at=now))
        s.commit()
    engine.dispose()

    monkeypatch.setattr(library_mod, "get_rekordbox_pid", lambda: 0)
    monkeypatch.setattr("pyrekordbox.db6.database.get_rekordbox_pid", lambda *a, **k: 0)
    cfg = Config(db_path=db_path, backup_dir=tmp_path / "backups", downloads_dir=tmp_path / "New Downloads",
                 unlock=False, home_dir=tmp_path / "rekordbox-mcp")
    cfg.downloads_dir.mkdir()
    return Library(cfg)
