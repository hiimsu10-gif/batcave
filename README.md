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

## Updating

- **On the page:** use the capture bar for quick ideas. Tap any item to edit it, or use "Make it a project" on an idea.
- **From Claude:** ask Claude to add or change items in "the Batcave". It writes to the artifact database directly.
- **Changing the page itself:** edit `dashboard/index.html` and republish it to the same artifact URL. The data stays in the database and is not affected.
