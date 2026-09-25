# Rekordbox connector for Claude Desktop

This is a local MCP server that connects Claude Desktop to your Rekordbox 6/7 library. It
reads and edits Rekordbox's own database (`master.db`) on your Mac through
[pyrekordbox](https://github.com/dylanljones/pyrekordbox). Nothing is uploaded anywhere.

## What you can ask Claude

**Build sets and playlists**
- "Build me a 90-minute deep house warm-up, 118 → 124 BPM, starting in 8A, skip anything I played this month."
- "What mixes well after *Night Drive*?"
- "Save that as a playlist called *Friday Warmup* in my *Gigs* folder."

**Organize and tag**
- "Tag everything I added this week with genre and energy My Tags. Show me the changes first."
- "Give all my 5-star techno a Blue color and add *#peak* to the comment."

**Clean up the library**
- "Find duplicates and tell me which copy to keep."
- "Which tracks have missing files, no hot cues, or no genre?"
- "What haven't I played in a year?"

**Stats**
- "Give me an overview of my library." / "What did I play at my last three gigs?" / "Top 25 most played this year."

**New music**
- "Scan my Dropbox New Downloads and import the new tracks into a *New This Week* playlist."
- *(with the Spotify connector)* "Check my Spotify playlist *Summer Finds* against Rekordbox and tell me what I'm missing." Missing tracks come back with Bandcamp, Beatport and SoundCloud links so you can buy them or grab free downloads.
- "Based on what I play most, which artists and genres should I check on Bandcamp and SoundCloud for new releases?"

## Making changes while Rekordbox is open

Rekordbox keeps the library in memory while it runs and overwrites the database when it saves.
Writing into `master.db` behind its back gets lost or corrupts the library, so the connector
works around that instead:

| What you ask for | Rekordbox closed | Rekordbox open |
|---|---|---|
| Search, stats, cleanup reports | Works | Works |
| New playlist / saved set / imports | Written into the library | Shows up under **rekordbox xml → Claude** in the sidebar. Right-click it and choose **Import Playlist** |
| Add tracks to an existing playlist | Written into the library | Arrives as "*name* (add these)" under rekordbox xml. Drag its tracks onto your playlist |
| Genre, rating, color, comments, My Tags | Written into the library | **Queued** and applied automatically about 30 seconds after you quit Rekordbox. They're there the next time you open it |

Ask *"what changes are pending?"* to see the queue, or *"cancel the pending changes"* to drop it.
The queue only runs while Claude Desktop is open. If you quit both, the queued edits are
applied the next time Claude Desktop starts with Rekordbox closed.

**One-time setup for the XML part** (Rekordbox 6/7):
1. **Preferences → Advanced → Database → rekordbox xml → Imported Library:** choose
   `~/Documents/rekordbox-mcp/claude-playlists.xml`. It's created the first time Claude makes a
   playlist while Rekordbox is open, so ask for one first.
2. **Preferences → View → Layout:** tick **rekordbox xml** so it appears in the left sidebar.
3. After Claude makes a playlist, click the refresh icon next to **rekordbox xml** to see it.

## Safety

- **Reading is safe anytime**, even with Rekordbox open.
- **Direct changes to the library only happen while Rekordbox is closed.** See above for what happens while it's open.
- **Every change makes a backup first** in `~/Documents/rekordbox-mcp-backups/<date-time>/`, holding
  `master.db` and `masterPlaylists6.xml`. The last 30 backups are kept.
  To undo a change: quit Rekordbox and copy both files from a backup back into `~/Library/Pioneer/rekordbox/`.
- It never deletes tracks or audio files. Tag edits can be previewed first (`dry_run`).
- Tracks it imports show up in Rekordbox **unanalyzed**. Select them and choose **Analyze Track**
  to get BPM, key and waveforms.

## Setup (Mac)

Open **Terminal**, paste this line and press Return:

```bash
curl -fsSL https://raw.githubusercontent.com/hiimsu10-gif/batcave/claude/festive-pascal-yrjn69/rekordbox-mcp/install.sh | bash
```

It installs `uv` if needed, downloads the connector to `~/rekordbox-mcp`, checks that it can
open your Rekordbox library, finds your Dropbox *New Downloads* folder, and adds the connector
to Claude Desktop (backing up your Claude settings first). Then quit Claude Desktop with ⌘Q and
reopen it. Run the same line again any time to update.

### Manual setup (if you'd rather do it by hand)

**1. Install `uv`:** `curl -LsSf https://astral.sh/uv/install.sh | sh`, then run `which uv` in a new
Terminal window and note the path.

**2. Get the code:** `git clone -b claude/festive-pascal-yrjn69 https://github.com/hiimsu10-gif/batcave.git ~/batcave`

**3. Test it:** `cd ~/batcave/rekordbox-mcp && uv run rekordbox-mcp --check`

**4. Add it to Claude Desktop.** In Claude Desktop, open **Settings → Developer → Edit Config**.
That opens `~/Library/Application Support/Claude/claude_desktop_config.json`. Add a
`rekordbox` entry, replacing `YOU` with your Mac username and using the `uv` path from step 1:

```json
{
  "mcpServers": {
    "rekordbox": {
      "command": "/Users/YOU/.local/bin/uv",
      "args": ["--directory", "/Users/YOU/batcave/rekordbox-mcp", "run", "rekordbox-mcp"],
      "env": {
        "REKORDBOX_MCP_DOWNLOADS_DIR": "/Users/YOU/Library/CloudStorage/Dropbox/New Downloads"
      }
    }
  }
}
```

If the file already has an `mcpServers` section, add the `"rekordbox": {...}` block inside it.

**5. Quit and reopen Claude Desktop.** Ask: *"Check my Rekordbox connection."*

### Optional settings (`env` block)

| Variable | What it does | Default |
|---|---|---|
| `REKORDBOX_MCP_DOWNLOADS_DIR` | Folder to scan for new downloads | `~/Library/CloudStorage/Dropbox/New Downloads`, then `~/Dropbox/New Downloads` |
| `REKORDBOX_DB_PATH` | Location of `master.db` | Found automatically |
| `REKORDBOX_MCP_BACKUP_DIR` | Where backups go | `~/Documents/rekordbox-mcp-backups` |
| `REKORDBOX_MCP_HOME` | Where the edit queue and `claude-playlists.xml` live | `~/Documents/rekordbox-mcp` |

## Troubleshooting

- **The server doesn't show up in Claude:** check the JSON for typos (a missing comma is the usual
  cause), and make sure `command` is the full path to `uv`. See Claude's logs in `~/Library/Logs/Claude/`.
- **Queued edits haven't applied:** make sure Rekordbox is fully quit (⌘Q, not just the window
  closed) and Claude Desktop is open. Then ask *"what changes are pending?"*.
- **Imported XML playlist shows tracks as missing:** the file moved after the playlist was made.
  Ask Claude to make the playlist again.
- **macOS asks for access to Dropbox or Documents:** allow it. Claude Desktop needs that to scan your downloads folder.
- **Scanning downloads is slow:** Dropbox "online-only" files get downloaded when they're scanned.
  Right-click the folder in Finder and choose **Make available offline**.
- **Tracks on an external drive show as "missing":** plug the drive in. They're only missing while it's disconnected.

## Tools

| Area | Tools |
|---|---|
| Status | `library_status`, `library_overview`, `backup_library` |
| Search | `search_tracks`, `get_track`, `suggest_next_tracks` |
| Playlists and sets | `list_playlists`, `get_playlist`, `create_playlist`, `add_to_playlist`, `build_set` |
| Tagging | `list_my_tags`, `update_tracks` |
| Cleanup | `find_duplicates`, `find_missing_files`, `find_incomplete_tracks`, `find_unplayed_tracks`, `find_tracks_without_cues` |
| History | `play_history`, `most_played` |
| While Rekordbox is open | `pending_changes`, `cancel_pending_changes` |
| New music | `scan_new_downloads`, `import_tracks`, `match_tracks`, `find_on_stores`, `discover_new_music` |

## Development

```bash
uv run --group dev pytest
```

The tests run against a small fake Rekordbox library, so Rekordbox isn't needed.
