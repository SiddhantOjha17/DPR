# DPR

I made this for a garment factory that was tracking production in an Excel workbook —
one sheet per brand, a free-text status column, manually-maintained subtotals, no
history. It worked, in the way something patched together over years works, but it had
one problem that couldn't be fixed inside Excel: a lot can't be in two stages at once.
The moment 500 pieces of a 1000-piece lot moved to finishing while the other 500 stayed
in washing, someone had to write the split into a free-text cell like "front ready back
pending" and just remember what it meant. That's the whole reason this app exists.

The factory owner isn't technical, and had already rejected one earlier attempt at this
for being too wide and complicated to actually use on the floor. So the rule I held
myself to the whole way through was: it has to look and feel like the Excel sheet he
already knows, or it won't get used, and then none of this matters.

## What it does

DPR tracks garment production lots as they move through a fixed sequence of stages
(Fabric Received → Cutting → Sewing → ... → FI Done), for seven brands. The core idea I
built it around: **don't store what stage a lot is in — store what moved, when, and how
much.** Current state is derived from that movement log, not the other way around.
That's what makes split lots (partial quantities sitting in different stages
simultaneously) a first-class case instead of a workaround.

Everything else follows from that one decision:

- **Main screen** — every open lot, grouped by stage, with subtotals per group and a
  grand total, filterable by brand. A split lot shows up in two groups with a "500 of
  1000" marker so it's never ambiguous.
- **Move pieces** — the daily action. Splitting is just moving less than the full
  quantity; I didn't build it as a special case.
- **Undo, for real** — I made undo work on any movement in a lot's history, not just the
  latest one, by posting a compensating movement in the opposite direction rather than
  editing history. It refuses the undo if the pieces already moved on somewhere else,
  rather than silently corrupting the chain.
- **Timeline and history** — every lot's side panel shows the full stage-by-stage
  history and a movement log, with an Undo button on each entry.
- **Archive** — a lot becomes shippable once all its pieces reach FI Done. Shipped lots
  leave the main list and land in a searchable archive, with an "Undo to FI" button for
  when something gets shipped by mistake.
- **Excel import and export** — I built the importer against the real production
  workbook (one sheet per brand, ~43 different spellings of the same statuses) with an
  ordered substring-matching rule table, and a reconciliation gate that refuses to
  proceed if the imported totals don't match what's expected. I made it repeatable
  later: Add mode skips rows whose CT number already exists instead of duplicating them,
  Replace mode wipes and reimports fresh, and there's a single-lot-add form for the days
  no one wants to touch Excel at all. Export mirrors the grouped view back out to
  `.xlsx`, since if this app ever breaks, the factory should be able to keep running on
  the exported sheet.
- **Analytics** — I redesigned this screen around a real narrative instead of a pile of
  tables: KPI tiles up top (open lots, pieces in the pipeline, shipped this week, average
  cycle time), a bottleneck bar chart for where things get stuck, a stacked chart for WIP
  over time, weekly throughput, an FI-date risk estimate (explicitly labeled as noisy
  until there's real history behind it), and a brand-comparison heatmap. I built the
  charts as plain server-rendered SVG — no charting library, no new JS dependency — using
  a validated color palette so the colors are actually colorblind-safe rather than picked
  by eye.
- **Access control** — once more than one person needed to use it, I added real logins
  (not just a self-reported name) and roles that are just four checkboxes that mix and
  match per role: move/undo pieces, edit or add a lot, ship or reopen a lot, and manage
  Settings. It's built so no one can lock themselves out — the app refuses to remove
  admin access from the last admin-capable person or role. Sessions invalidate whenever
  the app restarts, on purpose.
- **Every action is reversible, visibly** — I put a toast with an Undo button on every
  mutating action, expiring after a few seconds, without ever taking away the permanent
  undo that already lived in History, Archive, or Settings.

## How I built it

Python, FastAPI, and server-rendered Jinja2 templates with HTMX for interactivity — no
React, no build step, no npm. HTMX is the only vendored JS in the whole app, committed as
a plain static file so it works fully offline. SQLite in WAL mode is the entire database;
I didn't reach for Postgres or anything heavier because this never needed to be more than
a handful of people on one factory floor.

I kept the schema boring on purpose: `lots`, `positions` (the current-state cache), and
`movements` (the append-only truth), plus `brands`, `stages`, `sub_brands`, `users`, and
`roles`. I check one invariant after every write — the pieces sitting across all of a
lot's stages must equal its total quantity — and the app refuses to commit if it doesn't
hold. That single check is what makes the numbers trustworthy.

Everything mutating goes through one transaction helper so that invariant check never
gets skipped by accident, and there's a global error handler so an unexpected bug shows
up as a plain, honest message instead of a stack trace.

## Running it

```
uv sync
uv run main.py
```

That's it — it opens a browser to `http://localhost:8765` on its own. Other laptops on
the same wifi reach it at `http://<computer-name>:8765`.

## Testing

I wrote the test suite against the actual production workbook, not synthetic data — the
importer test asserts the exact reconciled totals (135 lots, 90,908 pieces, and every
per-brand number) against a copy of the real Excel file. Between that, the operations
tests, and the auth/permission tests, there are 150+ tests, run with:

```
uv run pytest -v
```

## Deploying it

I moved this off a personal laptop onto a dedicated on-prem Windows machine that stays on
all the time, reachable only from the office wifi — no internet exposure, no domain, no
HTTPS needed for that. It runs as a real Windows Service now (via NSSM) instead of
something that has to be double-clicked every morning: it starts on boot and restarts
itself if it ever crashes. The full step-by-step is in
[DEPLOYMENT.md](DEPLOYMENT.md), and updating it after a `git push` is one script:
`deploy/update.ps1`.

## What I deliberately left out

No cloud, no roles beyond what's built into the four permission checkboxes, no costing
or inventory features, no mobile UI — this only ever needed to work on a laptop screen
on one factory floor. The biggest real risk I know about and accepted: there's no offsite
backup by default, since everything is local-only. I built a weekly email-backup option
that's off by default and can be turned on in Settings if that safety net is ever needed.
