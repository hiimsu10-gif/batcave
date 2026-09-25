"""MCP server exposing a Rekordbox library to Claude Desktop."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from . import discovery
from .library import Library, LibraryError, rekordbox_running
from .setbuilder import build_set as order_set

INSTRUCTIONS = """\
Tools for the user's Rekordbox DJ library (tracks, playlists, tags, play history).

- Track IDs come from search results; always pass IDs, not titles, to tools that change things.
- Tools that change the library only work while Rekordbox is closed. Each change backs up
  master.db first and returns the backup folder. Before bulk edits (update_tracks on many
  tracks), run with dry_run=true, show the user the changes and ask for a go-ahead.
- Keys are reported in Camelot notation (8A, 9B...). BPM ramps and +/-1 Camelot moves make
  smooth sets.
- For tracks the user doesn't own, point them to the Bandcamp / Beatport / SoundCloud links
  returned by match_tracks or find_on_stores. Never help rip audio from streaming services.
"""

mcp = MCPServer("rekordbox", instructions=INSTRUCTIONS)
lib = Library()

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LibraryError as exc:
        return {"error": str(exc)}


# -- status & overview ----------------------------------------------------------------


@mcp.tool(annotations=READ)
def library_status() -> dict:
    """Check the connection: where the library is and whether Rekordbox is open (edits need it closed)."""
    def status():
        return {
            "database": str(lib.db_path),
            "rekordbox_running": rekordbox_running(),
            "backups_folder": str(lib.config.backup_dir),
            "downloads_folder": str(lib.config.downloads_dir) if lib.config.downloads_dir else "auto-detect",
        }
    return _run(status)


@mcp.tool(annotations=READ)
def library_overview() -> dict:
    """Stats for the whole library: track count, hours, top genres/artists, BPM ranges, keys,
    file types, tracks added per month, and how many are unanalyzed, unrated or never played."""
    return _run(lib.overview)


# -- search & tracks ------------------------------------------------------------------


@mcp.tool(annotations=READ)
def search_tracks(
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
    """Find tracks. All filters are optional and combine.

    text: words matched against artist/title/remixer/album/label/genre/comment.
    key: exact key, Camelot ("8A") or classic ("Am"). harmonic_with: keys that mix with this one.
    playlist: only search inside this playlist (name or id).
    added_after / not_played_since: dates as YYYY-MM-DD.
    sort_by: title, artist, bpm, key, rating, play_count, date_added, newest.
    """
    return _run(
        lib.search_tracks, text=text, artist=artist, genre=genre, bpm_min=bpm_min, bpm_max=bpm_max,
        key=key, harmonic_with=harmonic_with, min_rating=min_rating, my_tag=my_tag, color=color,
        playlist=playlist, added_after=added_after, not_played_since=not_played_since,
        sort_by=sort_by, limit=limit,
    )


@mcp.tool(annotations=READ)
def get_track(track_id: str) -> dict:
    """Everything about one track: tags, cue counts, which playlists it's in, whether the file exists."""
    return _run(lib.track_details, track_id)


@mcp.tool(annotations=READ)
def suggest_next_tracks(track_id: str, bpm_range_pct: float = 6.0, limit: int = 15) -> dict:
    """Tracks that mix well after this one: harmonically compatible key, BPM within +/- bpm_range_pct."""
    return _run(lib.suggest_next, track_id, bpm_range_pct=bpm_range_pct, limit=limit)


# -- playlists ------------------------------------------------------------------------


@mcp.tool(annotations=READ)
def list_playlists() -> dict:
    """All playlists, folders and smart playlists with their folder path and track counts."""
    return _run(lambda: {"playlists": lib.list_playlists()})


@mcp.tool(annotations=READ)
def get_playlist(playlist: str) -> dict:
    """Tracks in a playlist (name or id), in order."""
    return _run(lib.playlist_tracks, playlist)


@mcp.tool(annotations=WRITE)
def create_playlist(name: str, track_ids: list[str], folder: str | None = None) -> dict:
    """Create a playlist with these tracks, in this order. `folder` is created if it doesn't exist.
    Requires Rekordbox to be closed; backs up the library first."""
    return _run(lib.create_playlist, name, track_ids, folder=folder)


@mcp.tool(annotations=WRITE)
def add_to_playlist(playlist: str, track_ids: list[str], skip_existing: bool = True) -> dict:
    """Append tracks to an existing playlist. Requires Rekordbox to be closed; backs up first."""
    return _run(lib.add_to_playlist, playlist, track_ids, skip_existing=skip_existing)


# -- set building ---------------------------------------------------------------------


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False))
def build_set(
    duration_minutes: float = 60,
    bpm_start: float | None = None,
    bpm_end: float | None = None,
    start_key: str | None = None,
    start_track_id: str | None = None,
    genre: str | None = None,
    my_tag: str | None = None,
    playlist: str | None = None,
    bpm_min: float | None = None,
    bpm_max: float | None = None,
    min_rating: int | None = None,
    skip_played_within_days: int | None = None,
    save_as_playlist: str | None = None,
) -> dict:
    """Build an ordered DJ set: ramps BPM from bpm_start to bpm_end and keeps keys harmonic
    (Camelot), avoiding the same artist back to back.

    Candidates come from the library filtered by genre / my_tag / playlist / BPM / rating.
    skip_played_within_days leaves out tracks played recently. If save_as_playlist is given
    the set is saved as a new playlist (Rekordbox must be closed); otherwise it's a preview.
    """
    def run():
        import datetime as dt

        not_played_since = None
        if skip_played_within_days:
            not_played_since = (dt.date.today() - dt.timedelta(days=skip_played_within_days)).isoformat()
        lo = bpm_min if bpm_min is not None else (min(bpm_start, bpm_end or bpm_start) * 0.94 if bpm_start else None)
        hi = bpm_max if bpm_max is not None else (max(bpm_start, bpm_end or bpm_start) * 1.06 if bpm_start else None)
        pool = lib.search_tracks(
            genre=genre, my_tag=my_tag, playlist=playlist, bpm_min=lo, bpm_max=hi,
            min_rating=min_rating, not_played_since=not_played_since, limit=100_000,
        )["tracks"]
        result = order_set(pool, duration_minutes, bpm_start=bpm_start, bpm_end=bpm_end,
                           start_key=start_key, start_track_id=start_track_id)
        result["candidates"] = len(pool)
        result["tracks"] = [
            {k: t.get(k) for k in ("position", "id", "artist", "title", "bpm", "camelot", "duration", "transition")}
            for t in result["tracks"]
        ]
        if save_as_playlist and result["tracks"]:
            result["saved"] = lib.create_playlist(save_as_playlist, [t["id"] for t in result["tracks"]])
        return result
    return _run(run)


# -- tagging --------------------------------------------------------------------------


@mcp.tool(annotations=READ)
def list_my_tags() -> dict:
    """The My Tag categories and tags in Rekordbox, with how many tracks use each, plus track colors."""
    return _run(lambda: {"my_tags": lib.list_my_tags(), "colors": lib.list_colors()})


@mcp.tool(annotations=WRITE)
def update_tracks(
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
    """Edit tracks: genre, comment (replace, or append_comment to add text), rating 0-5,
    color (a name from list_my_tags; "" clears it), and My Tags (must already exist).

    Use dry_run=true to preview exactly what would change. Requires Rekordbox to be closed
    when applying; backs up the library first.
    """
    return _run(
        lib.update_tracks, track_ids, genre=genre, comment=comment, append_comment=append_comment,
        rating=rating, color=color, add_my_tags=add_my_tags, remove_my_tags=remove_my_tags, dry_run=dry_run,
    )


# -- cleanup --------------------------------------------------------------------------


@mcp.tool(annotations=READ)
def find_duplicates(limit: int = 50) -> dict:
    """Tracks that appear more than once (same artist + title), with a suggested copy to keep
    (lossless / highest bitrate / most played)."""
    return _run(lib.find_duplicates, limit=limit)


@mcp.tool(annotations=READ)
def find_missing_files(limit: int = 100) -> dict:
    """Tracks whose audio file can't be found (moved, deleted, or on an unplugged drive)."""
    return _run(lib.find_missing_files, limit=limit)


@mcp.tool(annotations=READ)
def find_incomplete_tracks(fields: list[str] | None = None, limit: int = 100) -> dict:
    """Tracks missing info. fields: any of genre, key, bpm, artist, rating, my_tags, label, comment."""
    return _run(lib.find_incomplete, fields=fields, limit=limit)


@mcp.tool(annotations=READ)
def find_unplayed_tracks(days: int = 365, limit: int = 100) -> dict:
    """Tracks not played in the last `days` days (and added before then), oldest first."""
    return _run(lib.find_unplayed, days=days, limit=limit)


@mcp.tool(annotations=READ)
def find_tracks_without_cues(limit: int = 100) -> dict:
    """Tracks with no hot cues set yet."""
    return _run(lib.find_without_cues, limit=limit)


# -- history --------------------------------------------------------------------------


@mcp.tool(annotations=READ)
def play_history(days: int = 90, include_tracks: bool = True, limit: int = 20) -> dict:
    """Recent DJ sessions from Rekordbox History, newest first, with the tracks played."""
    return _run(lib.play_history, days=days, include_tracks=include_tracks, limit=limit)


@mcp.tool(annotations=READ)
def most_played(limit: int = 25, days: int | None = None) -> dict:
    """Most-played tracks, all time or within the last `days` days."""
    return _run(lib.most_played, limit=limit, days=days)


# -- new downloads, Spotify matching, discovery ---------------------------------------


@mcp.tool(annotations=READ)
def scan_new_downloads(folder: str | None = None, limit: int = 200) -> dict:
    """Audio files in the downloads folder (default: Dropbox 'New Downloads') that aren't in
    Rekordbox yet, with their tags and any likely duplicate already in the library."""
    return _run(lib.scan_downloads, folder=folder, limit=limit)


@mcp.tool(annotations=WRITE)
def import_tracks(file_paths: list[str], playlist: str | None = None) -> dict:
    """Add audio files to the Rekordbox collection, optionally into a playlist (created if needed).
    Rekordbox must be closed. Afterwards the tracks need analyzing in Rekordbox for BPM/key."""
    return _run(lib.import_files, file_paths, playlist=playlist)


@mcp.tool(annotations=READ)
def match_tracks(tracks: list[str], min_score: float = 0.8) -> dict:
    """Check a tracklist against the library, e.g. a Spotify playlist or a set someone posted.
    Pass one "Artist - Title" string per track. Missing tracks come back with Bandcamp,
    Beatport and SoundCloud links to buy or download them legitimately."""
    return _run(lib.match_tracks, tracks, min_score=min_score)


@mcp.tool(annotations=READ)
def find_on_stores(artist: str = "", title: str = "") -> dict:
    """Bandcamp, Beatport and SoundCloud search links for a track."""
    return discovery.store_links(artist, title)


@mcp.tool(annotations=READ)
def discover_new_music(artists: int = 10, genres: int = 5, based_on: str = "plays") -> dict:
    """Starting points for finding new tracks: the artists and genres you play most
    (based_on="plays") or added most recently (based_on="recent"), each with Bandcamp,
    SoundCloud and Beatport links to check for new releases."""
    return _run(lib.discovery_sources, artists=artists, genres=genres, based_on=based_on)


@mcp.tool(annotations=WRITE)
def backup_library() -> dict:
    """Make a backup copy of the Rekordbox library right now."""
    return _run(lambda: {"backup": str(lib.backup())})


def check() -> int:
    """`rekordbox-mcp --check`: confirm the library opens, without starting the server."""
    try:
        overview = lib.overview()
    except LibraryError as exc:
        print(f"Problem: {exc}")
        return 1
    print(f"Library:  {lib.db_path}")
    print(f"Tracks:   {overview['tracks']} ({overview['total_hours']} hours), playlists: {overview['playlists']}")
    print(f"Rekordbox running: {'yes (edits will wait until you quit it)' if rekordbox_running() else 'no'}")
    try:
        print(f"Downloads folder: {lib.downloads_dir()}")
    except LibraryError as exc:
        print(f"Downloads folder: not found. {exc}")
    print("All good. Add the server to Claude Desktop (see README).")
    return 0


def main() -> None:
    import sys

    if "--check" in sys.argv[1:]:
        raise SystemExit(check())
    mcp.run("stdio")


if __name__ == "__main__":
    main()
