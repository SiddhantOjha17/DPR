# Deploying DPR on a dedicated on-prem Windows server

This runbook sets DPR up as an always-on Windows Service on a machine your company
already owns, reachable only from your office wifi (no internet exposure, no domain, no
HTTPS — none of that is needed for a LAN-only deployment). It **fully replaces** the
original "double-click DPR.exe on the owner's laptop" model with a proper unattended
service that starts on boot and restarts itself if it ever crashes.

This is a **fresh install** — the server starts with an empty database. Whoever owns this
instance sets their own Owner password on first run, then imports or enters their own
data. It is not a copy of anyone else's existing data.

Follow these steps in order on the server itself.

## 1. Prerequisites

- A Windows machine you have administrator access to, connected to the office network
  that should be able to reach DPR.
- Enough disk space for Python, the app, and a SQLite database that will grow over time
  (trivial at the scale this app runs at — a few hundred MB is more than enough).

## 2. Install Python and `uv`

Install Python 3.11 or later from [python.org](https://python.org), then install `uv`
(the tool this project already uses for dependencies) by following the instructions at
[docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) — on
Windows this is a single PowerShell command from that page.

Confirm both are on PATH:

```powershell
python --version
uv --version
```

## 3. Get the code onto the server

```powershell
cd C:\
git clone <your-repo-url> dpr
cd dpr
uv sync
```

`uv sync` installs FastAPI, uvicorn, openpyxl, and everything else from
`pyproject.toml` into a local virtual environment — no PyInstaller build needed for this
path. A dedicated, admin-maintained server is a better fit for "`git pull` + restart to
update" (see step 9) than rebuilding a single-file `.exe` on every change.

## 4. Choose a data folder (starts empty, on purpose)

Pick a folder for the database, e.g. `C:\ProgramData\DPR`. You don't need to create or
copy anything into it — the app creates the schema and seeds default stages/brands/the
Owner role on its first boot, and the lots table starts genuinely empty. You (or whoever
owns this instance) will set a password at `/setup` on first visit, then use **Import**
(bulk Excel upload or the single-lot-add form) to bring in real data.

You'll set this path as the `DPR_DATA_DIR` environment variable when registering the
service in the next step — the app always respects that variable when it's set (see
`app/config.py`), so there's nothing else to configure here.

## 5. Install NSSM and register the Windows Service

[NSSM](https://nssm.cc/) ("the Non-Sucking Service Manager") wraps any command as a real
Windows Service — auto-starts on boot, restarts itself if the process ever exits or
crashes. Download it from nssm.cc and put `nssm.exe` somewhere on PATH.

Find the full path to `uv` first (`where.exe uv`), then register the service:

```powershell
nssm install DPR "C:\path\to\uv.exe" "run main.py"
nssm set DPR AppDirectory "C:\dpr"
nssm set DPR AppEnvironmentExtra "DPR_DATA_DIR=C:\ProgramData\DPR" "DPR_AUTO_OPEN_BROWSER=0"
nssm set DPR AppExit Default Restart
nssm set DPR Start SERVICE_AUTO_START
nssm start DPR
```

- `DPR_AUTO_OPEN_BROWSER=0` stops the app from trying to open a browser window — that
  only makes sense when a person just double-clicked the icon on their own laptop, not
  when Windows starts this unattended at boot with no one logged in.
- `AppExit Default Restart` is what turns the in-app "Restart App" button (Settings-admin
  only) into an actual restart: it exits the process, and NSSM brings it straight back up.

If you registered the service under a different name than `DPR`, update the
`$ServiceName` line in `deploy/update.ps1` to match.

## 6. Open the firewall port

```powershell
netsh advfirewall firewall add rule name="DPR" dir=in action=allow protocol=TCP localport=8765
```

Run this once, directly, as an administrator. (The original design had the app try to
self-elevate and add this rule on first run for a non-technical owner double-clicking an
icon — that flow doesn't apply here; this is a deliberate one-time setup step done by
whoever has admin rights on the server.)

## 7. If your office has two separate wifi networks

Whether devices on "the other" wifi can reach this server depends on whether both
networks are actually the *same local subnet* — not just whether they share one internet
connection. A single ISP feeding two separate wifi routers is very often two **separate**
subnets (each router does its own NAT), even though there's only one connection upstream.
If that's the case, a device on Wifi A cannot reach a server on Wifi B by default,
regardless of anything in this app.

The usual fix, if both networks are meant to reach each other: put the second wifi
device into **access-point/bridge mode** instead of full router mode, so both SSIDs join
one shared subnet off the same upstream connection. Most consumer and small-office
routers support this as a single setting. This is a network change, not an app change —
test it directly once set up: from a device on the other wifi, try
`http://<server-hostname>:8765`. If it doesn't load, this is almost certainly why.

## 8. Verify

- `nssm status DPR` (or `services.msc`) shows the service **Running**.
- From another device on the office wifi: `http://<server-hostname>:8765` loads and
  redirects to `/setup`.
- Complete `/setup`, confirm you land on an empty main screen ready for Import.
- Reboot the server, confirm the service comes back up on its own.
- Simulate a crash (`taskkill /F /IM python.exe` or similar, matched to however `uv run`
  shows up in Task Manager) and confirm NSSM restarts it within a few seconds. Everyone's
  login session will be invalidated when this happens — that's expected, not a bug:
  sessions are deliberately tied to the process's lifetime, so a restart always forces a
  fresh login rather than trusting a stale session.

## 9. Updating later

Push your changes to git as usual, then on the server:

```powershell
cd C:\dpr
.\deploy\update.ps1
```

This pulls the latest code, re-syncs dependencies, and restarts the service. No CI
system, no webhook, no internet exposure needed — the server has none of those, so this
is a deliberate pull triggered by whoever's on-site, not push-triggered automation.

## 10. Logs

Set log file paths when registering the service, so there's somewhere to look without
needing a terminal open on the server:

```powershell
nssm set DPR AppStdout C:\ProgramData\DPR\logs\stdout.log
nssm set DPR AppStderr C:\ProgramData\DPR\logs\stderr.log
```
