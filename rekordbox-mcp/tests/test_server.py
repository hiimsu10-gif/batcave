import asyncio

from rekordbox_mcp import server

def test_tools_registered():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert {"search_tracks", "build_set", "create_playlist", "update_tracks", "find_duplicates",
            "scan_new_downloads", "match_tracks", "discover_new_music"} <= names

def test_build_set_tool(rb, monkeypatch):
    monkeypatch.setattr(server, "lib", rb)
    out = server.build_set(duration_minutes=15, bpm_start=120, bpm_end=124)
    assert out["candidates"] >= 3 and out["tracks"][0]["position"] == 1
    saved = server.build_set(duration_minutes=10, bpm_start=122, save_as_playlist="Test Set")
    assert saved["saved"]["tracks_added"] == len(saved["tracks"])

def test_errors_are_returned_not_raised(rb, monkeypatch):
    monkeypatch.setattr(server, "lib", rb)
    assert "error" in server.get_track("nope")


def test_watcher_applies_after_rekordbox_quits(rb, monkeypatch):
    import threading
    import time

    from rekordbox_mcp import library as library_mod

    monkeypatch.setattr(server, "lib", rb)
    running = {"v": True}
    monkeypatch.setattr(library_mod, "get_rekordbox_pid", lambda: 1 if running["v"] else 0)
    monkeypatch.setattr(server, "rekordbox_running", lambda: running["v"])
    rb.update_tracks(["102"], rating=2)
    stop = threading.Event()
    t = threading.Thread(target=server.watch_for_rekordbox_quit, kwargs={"interval": 0.05, "stop": stop})
    t.start()
    try:
        time.sleep(0.3)
        assert rb.pending.items()  # still open: nothing applied
        running["v"] = False
        deadline = time.time() + 5
        while rb.pending.items() and time.time() < deadline:
            time.sleep(0.05)
    finally:
        stop.set()
        t.join()
    assert rb.track_details("102")["rating"] == 2
    listed = server.pending_changes()
    assert listed["pending"] == [] and listed["recently_applied"][0]["applied"]
