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

## Safety

- **Reading is safe anytime**, even with Rekordbox open.
- **Changes only happen while Rekordbox is closed.** If it's open, Claude will ask you to quit it first.
- **Every change makes a backup first** in `~/Documents/rekordbox-mcp-backups/<date-time>/`, holding
  `master.db` and `masterPlaylists6.xml`. The last 30 backups are kept.
  To undo a change: quit Rekordbox and copy both files from a backup back into `~/Library/Pioneer/rekordbox/`.
- It never deletes tracks or audio files. Tag edits can be previewed first (`dry_run`).
- Tracks it imports show up in Rekordbox **unanalyzed**. Select them and choose **Analyze Track**
  to get BPM, key and waveforms.

## Setup (Mac, about 10 minutes)

**1. Install `uv`** (it runs Python apps). Open Terminal and paste:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close Terminal, open a new one, and run `which uv`. Note the path it prints, e.g. `/Users/su/.local/bin/uv`.

**2. Get this code** onto your Mac, e.g. into your home folder:

```bash
git clone https://github.com/hiimsu10-gif/batcave.git ~/batcave
```

(Or download the repo as a ZIP from GitHub and unzip it to `~/batcave`.)

**3. Test it:**

```bash
cd ~/batcave/rekordbox-mcp && uv run rekordbox-mcp --check
```

You should see your track and playlist counts. The first run takes a minute while it installs.

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

## Troubleshooting

- **The server doesn't show up in Claude:** check the JSON for typos (a missing comma is the usual
  cause), and make sure `command` is the full path to `uv`. See Claude's logs in `~/Library/Logs/Claude/`.
- **"Rekordbox is open":** quit Rekordbox fully (⌘Q) and ask again.
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
| New music | `scan_new_downloads`, `import_tracks`, `match_tracks`, `find_on_stores`, `discover_new_music` |

## Development

```bash
uv run --group dev pytest
```

The tests run against a small fake Rekordbox library, so Rekordbox isn't needed.
