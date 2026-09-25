import pytest

from rekordbox_mcp import library as library_mod
from rekordbox_mcp.library import LibraryError


def test_track_fields(rb):
    t = next(t for t in rb.all_tracks() if t["id"] == "101")
    assert t["artist"] == "Alpha" and t["bpm"] == 122.0 and t["camelot"] == "8A"
    assert t["duration"] == "6:00" and t["rating"] == 5
    assert t["last_played"] is not None  # played in the recent history session
    unkeyed = next(t for t in rb.all_tracks() if t["id"] == "107")
    assert unkeyed["key"] is None and unkeyed["bpm"] is None and unkeyed["genre"] is None


def test_search_filters(rb):
    ids = lambda r: [t["id"] for t in r["tracks"]]
    assert ids(rb.search_tracks(genre="techno", sort_by="bpm")) == ["106", "103"]
    assert set(ids(rb.search_tracks(bpm_min=121, bpm_max=124))) == {"101", "102", "104"}
    assert set(ids(rb.search_tracks(harmonic_with="Am"))) == {"101", "102", "104", "105"}
    assert ids(rb.search_tracks(key="4A")) == ["103"]
    assert ids(rb.search_tracks(text="night drive")) == ["103"]
    assert ids(rb.search_tracks(my_tag="dark")) == ["103"]
    assert ids(rb.search_tracks(playlist="Warmup", sort_by="rating")) == ["101", "102"]
    with pytest.raises(LibraryError):
        rb.search_tracks(key="H#")


def test_track_details(rb):
    d = rb.track_details("101")
    assert d["hot_cues"] == 1 and d["in_playlists"] == ["Warmup"] and d["file_exists"]
    assert not rb.track_details("105")["file_exists"]


def test_playlists(rb):
    pls = rb.list_playlists()
    assert [p["path"] for p in pls] == ["Sets", "Sets/Warmup"]
    pl = rb.playlist_tracks("warmup")
    assert [t["id"] for t in pl["tracks"]] == ["102", "101"]
    with pytest.raises(LibraryError):
        rb.playlist_tracks("Sets")


def test_create_and_extend_playlist(rb):
    res = rb.create_playlist("Peak Time", ["106", "103"], folder="Gigs")
    assert res["tracks_added"] == 2
    assert (rb.config.backup_dir.iterdir().__next__() / "master.db").exists()
    pl = rb.playlist_tracks("Peak Time")
    assert [t["id"] for t in pl["tracks"]] == ["106", "103"]
    assert "Gigs/Peak Time" in [p["path"] for p in rb.list_playlists()]
    res = rb.add_to_playlist("Peak Time", ["103", "101"])
    assert res == {**res, "added": 1, "skipped_already_in_playlist": 1}
    assert [t["id"] for t in rb.playlist_tracks("Peak Time")["tracks"]] == ["106", "103", "101"]


def test_update_tracks_dry_run_then_apply(rb):
    preview = rb.update_tracks(["103", "105"], genre="Techno", rating=4, add_my_tags=["Dark"], dry_run=True)
    assert preview["applied"] is False and preview["tracks_changing"] == 2
    assert rb.track_details("105")["genre"] == "Deep House"
    res = rb.update_tracks(["103", "105"], genre="Techno", rating=4, color="Blue", add_my_tags=["Dark"],
                           append_comment="#peak")
    assert res["applied"]
    t = rb.track_details("105")
    assert (t["genre"], t["rating"], t["color"], t["my_tags"], t["comment"]) == ("Techno", 4, "Blue", ["Dark"], "#peak")
    rb.update_tracks(["103"], remove_my_tags=["Dark"], genre="Minimal")
    t = rb.track_details("103")
    assert t["my_tags"] == [] and t["genre"] == "Minimal"
    with pytest.raises(LibraryError, match="don't exist"):
        rb.update_tracks(["103"], add_my_tags=["Nope"])


def test_writes_refused_while_rekordbox_open(rb, monkeypatch):
    monkeypatch.setattr(library_mod, "get_rekordbox_pid", lambda: 1234)
    with pytest.raises(LibraryError, match="Quit Rekordbox"):
        rb.create_playlist("X", ["101"])
    assert not rb.config.backup_dir.exists()


def test_cleanup(rb):
    d = rb.find_duplicates()
    assert d["duplicate_groups"] == 1
    assert {c["id"] for c in d["groups"][0]["copies"]} == {"101", "104"}
    assert d["groups"][0]["suggest_keep_id"] == "101"  # more plays
    assert [t["id"] for t in rb.find_missing_files()["tracks"]] == ["105"]
    inc = rb.find_incomplete(["genre", "key"])
    assert inc["counts"] == {"genre": 1, "key": 1}
    unplayed = {t["id"] for t in rb.find_unplayed(days=365)["tracks"]}
    assert "101" not in unplayed and "106" not in unplayed and {"103", "105"} <= unplayed
    assert "107" not in unplayed  # added recently
    assert "101" not in {t["id"] for t in rb.find_without_cues()["tracks"]}


def test_stats(rb):
    o = rb.overview()
    assert o["tracks"] == 7 and o["not_analyzed"] == 1 and o["playlists"] == 2
    h = rb.play_history(days=30)
    assert h["sessions"] == 1 and [t["id"] for t in h["history"][0]["tracks"]] == ["101", "106"]
    top = rb.most_played(limit=2)
    assert [t["id"] for t in top["tracks"]] == ["101", "106"]
    recent = rb.most_played(days=30)
    assert {t["id"] for t in recent["tracks"]} == {"101", "106"}


def test_downloads_scan_and_import(rb):
    inbox = rb.config.downloads_dir
    (inbox / "Zeta - Fresh Cut.mp3").write_bytes(b"\0" * 100)
    (inbox / "Alpha - Sunrise.wav").write_bytes(b"\0" * 100)
    (inbox / "notes.txt").write_text("x")
    scan = rb.scan_downloads()
    assert scan["new_files"] == 2
    by_file = {f["file"]: f for f in scan["files"]}
    assert by_file["Alpha - Sunrise.wav"]["possible_duplicate_of"]["id"] == "101"
    assert "possible_duplicate_of" not in by_file["Zeta - Fresh Cut.mp3"]
    res = rb.import_files([str(inbox / "Zeta - Fresh Cut.mp3")], playlist="New This Week")
    assert len(res["added"]) == 1 and "Analyze" in res["next_step"]
    new = rb.playlist_tracks("New This Week")["tracks"]
    assert [(t["artist"], t["title"]) for t in new] == [("Zeta", "Fresh Cut")]
    assert rb.scan_downloads()["new_files"] == 1
    again = rb.import_files([str(inbox / "Zeta - Fresh Cut.mp3")])
    assert again["added"] == [] and len(again["skipped_already_in_library"]) == 1
    with pytest.raises(LibraryError):
        rb.import_files([str(inbox / "missing.mp3")])


def test_match_and_discovery(rb):
    m = rb.match_tracks(["Alpha - Sunrise", "Gamma - Warehouse (Extended Mix)", "Nobody - Unknown Song"])
    assert m["in_library"] == 2 and m["missing"] == 1
    links = m["missing_tracks"][0]["where_to_get_it"]
    assert links["bandcamp"].startswith("https://bandcamp.com/search?q=Nobody+Unknown+Song")
    disc = rb.discovery_sources(artists=2, genres=1)
    assert [a["artist"] for a in disc["artists"]] == ["Alpha", "Gamma"]
    assert disc["genres"][0]["genre"] == "House"


def test_backups_are_pruned(rb, monkeypatch):
    monkeypatch.setattr(library_mod, "MAX_BACKUPS", 2)
    for _ in range(4):
        rb.backup()
    assert len(list(rb.config.backup_dir.iterdir())) == 2
