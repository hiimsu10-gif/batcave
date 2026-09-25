# batcave

Su's command center for every idea, project, task and gig in one place.

- **Live dashboard:** https://claude.ai/artifact/WZ481fbgBtkSD6c9ykzsg2 (private)
- **Source:** [`dashboard/index.html`](dashboard/index.html). This is a single-file page published as a Claude artifact with a shared database (`db` capability).

## What it tracks

| Collection | Fields |
|---|---|
| `projects` | title, vertical, status (developing / active / paused / done), next, due, link, notes |
| `ideas` | title, vertical, stage (spark / developing / promoted / shelved), note, link |
| `tasks` | title, projectId, priority (high / med / low), due, done, vertical |
| `gigs` | title, kind (booking / lead / release / income), status (lead → pitched → confirmed → played → paid / passed), date, amount, contact, link, notes |

Verticals: `music` (Suprm Sounds), `film` (Golden Hour), `content` (Side B & Sidenotes), `web` (Web + GBP), `biz` (Aurelia Corp), `personal`.

## Rekordbox check (run on the Mac)

`tools/rekordbox_itr_check.py` compares the ITR set lists in Dropbox (`Setlists/ITR Ep*Setlists.md`) with the Rekordbox library. For each track it reports whether it's imported, Rekordbox's key and BPM, and whether the file is on disk, online-only or missing.

```sh
pip3 install pyrekordbox
python3 tools/rekordbox_itr_check.py              # writes Setlists/ITR Rekordbox Check.md
python3 tools/rekordbox_itr_check.py --download   # also downloads online-only Dropbox files
```

Close Rekordbox first. On Rekordbox 7, if the database won't open, run `python3 -m pyrekordbox download-key` once.

## Updating

- **On the page:** use the capture bar for quick ideas. Tap any item to edit it, or use "Make it a project" on an idea.
- **From Claude:** ask Claude to add or change items in "the Batcave". It writes to the artifact database directly.
- **Changing the page itself:** edit `dashboard/index.html` and republish it to the same artifact URL. The data stays in the database and is not affected.
