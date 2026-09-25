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
