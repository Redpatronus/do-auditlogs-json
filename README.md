# DO Audit Scraper

Downloads the **DigitalOcean audit log** (the account's security / activity history) and appends
new events to an **NDJSON** file, one JSON event per line. Built to run on a server from cron or
systemd and to feed **Wazuh** (integration is the next phase).

Inspired by [ionsec/DO-Audit-Log-Scraper](https://github.com/ionsec/DO-Audit-Log-Scraper).

> DigitalOcean has no API for audit logs, so this is a scraper of the web console and **not an
> official API**. If DigitalOcean changes the page, it may need adjusting. Use it only on your own
> account and in accordance with DigitalOcean's terms.

## Contents

- [How it works](#how-it-works)
- [Before you start](#before-you-start)
- [Quick start (server)](#quick-start-server)
- [Quick start (macOS, for development)](#quick-start-macos-for-development)
- [Configuration](#configuration)
- [Commands](#commands)
- [Output](#output)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Project layout and development](#project-layout-and-development)

## How it works

1. Starts Chromium (Playwright) and logs in with e-mail + password + TOTP code.
2. Opens the audit log page and captures the responses of the page's own `GetAuditActions` GraphQL
   operation (exact time, unique ID, action, user, IP), paging with the "next" button.
3. Writes only **new** events (deduplicated by the ID assigned by DigitalOcean).

The session (cookies) is cached in `data/storage_state.json` and reused, so it does not log in on
every run. Writing happens only after a run completes, so an error midway leaves no gap in the data.

## Before you start

| You need | Notes |
|---|---|
| A DigitalOcean account that logs in with **e-mail + password** and **TOTP 2FA** | Google / GitHub SSO is not supported. Prefer a **dedicated read-only team member** with its own TOTP secret over a personal owner account. |
| The **TOTP secret** | The text key shown under the QR code when enabling the authenticator app (letters A–Z, digits 2–7; a full `otpauth://…` URI also works). It is shown only once, so store it. **Not** the 6-digit code and not the backup codes. |
| The **audit log page path** | Depends on the account type, see [below](#which-audit-page-path). |
| Debian/Ubuntu server with root access | For the server setup. Python 3.11+, Xvfb and the Chromium libraries are installed by the script. |

### Which audit page path?

The page that shows the table of events (time, action, user, IP) differs by account type. Log in
with the account in a normal browser and find where the table is:

| Account | `DOAL_AUDIT_PATH` |
|---|---|
| Lower permissions | `/account/security` |
| Higher permissions (**Security** in the left menu) | `/settings/security` |
| Default if unset | `/security/history` (DigitalOcean redirects it to the dashboard for some accounts) |

If the scraper ends on `…/dashboard?i=…`, the path is wrong for that account.

## Quick start (server)

One script prepares everything, another one only runs the scraper (ideal for cron).

```bash
# 1. Put the project somewhere (e.g. git clone <url> /opt/do-audit), go there, run as root:
cd /opt/do-audit
sudo ./scripts/install.sh              # packages, user, venv, dependencies, Chromium + its libs, .env
# add --systemd to also install the systemd timer (every 15 minutes)

# 2. Fill in .env: DOAL_EMAIL, DOAL_PASSWORD, DOAL_TOTP_SECRET, DOAL_AUDIT_PATH
sudo -u doaudit nano .env

# 3. Test, then run (still in the project directory)
sudo -u doaudit ./scripts/run.sh login-test     # expect: LOGIN OK
sudo -u doaudit ./scripts/run.sh                # = scrape
```

The examples use `/opt/do-audit`; any other location works the same, just `cd` into it first. Use
absolute paths (`/opt/do-audit/scripts/run.sh`) in cron and systemd.

`scripts/install.sh` is idempotent (re-run after updating the code). It creates the service user
`doaudit` (`--user NAME` for another one) and gives it ownership of the project, `data/` mode `700`
and `.env` mode `600`. The project must be on a path that user can reach (e.g. `/opt/do-audit`, not
`/root`) and the scripts must sit directly in `/opt/do-audit/scripts/`, not in a nested folder.

`scripts/run.sh [args]` only runs `do-audit` (default `scrape`). It works from any directory, needs
no prepared environment, returns do-audit's exit code, and when started as root it switches to the
project owner so no root-owned files appear in `data/`.

**Scheduling** (pick one):

```bash
# cron
sudo crontab -u doaudit -e
*/15 * * * * /opt/do-audit/scripts/run.sh >> /opt/do-audit/data/run.log 2>&1

# or systemd
sudo ./scripts/install.sh --systemd
systemctl list-timers do-audit.timer
journalctl -u do-audit.service -f
```

The server has no display, so the scraper starts a virtual one (Xvfb) and runs a regular,
non-headless Chromium in it (headless is blocked by Cloudflare). Cloudflare may repeat its
challenge for a datacenter IP address, so verify a real run on the server itself.

## Quick start (macOS, for development)

```bash
./scripts/setup.sh                 # finds Python >= 3.11, creates .venv, installs deps and Chromium, creates .env
source .venv/bin/activate
do-audit login                     # manual login in a window, saves the session (no credentials needed in .env)
do-audit scrape --headed
make test                          # optional
```

## Configuration

Everything is set in `.env` (template: `.env.example`) as `KEY=value`, with no spaces around `=` and
usually no quotes. Values with special characters (`#`, `$`) go in single quotes:
`DOAL_PASSWORD='ab#c$d'`. Empty values are ignored. **Never commit `.env`.**

### Credentials (required for automatic login)

| Variable | Description |
|---|---|
| `DOAL_EMAIL` | DigitalOcean account e-mail |
| `DOAL_PASSWORD` | password |
| `DOAL_TOTP_SECRET` | TOTP secret, see [Before you start](#before-you-start) |

### Other settings

| Variable | Default | Description |
|---|---|---|
| `DOAL_AUDIT_PATH` | `/security/history` | Audit log page, see [Which audit page path?](#which-audit-page-path) |
| `DOAL_HEADLESS` | `false` | Keep `false`; headless is blocked by Cloudflare. |
| `DOAL_SESSION_MAX_AGE_DAYS` | `7` | After how many days the cached session is dropped and a fresh login is done. |
| `DOAL_SESSION_MAX_AGE_HOURS` | empty | The same in hours. **Set only one of the two**; both empty = 7 days. Must not exceed the session lifetime configured in DigitalOcean. |
| `DOAL_OUTPUT_PATH` | `data/audit_logs.ndjson` | output file |
| `DOAL_STATE_PATH` | `data/state.json` | deduplication state (seen IDs) |
| `DOAL_STORAGE_STATE_PATH` | `data/storage_state.json` | cached session (cookies, **secret**) |
| `DOAL_MAX_PAGES` | `100` | maximum pages per run (1 page = 25 events) |
| `DOAL_PAGE_DELAY_S` | `1.5` | pause between pages; increase on rate-limit errors |
| `DOAL_NAV_TIMEOUT_MS` | `45000` | navigation timeout |
| `DOAL_LOG_LEVEL` | `INFO` | log level |
| `DOAL_LOG_JSON` | `true` | JSON logs on stderr |

Selectors (`DOAL_TABLE_SELECTOR`, `DOAL_NEXT_BUTTON_SELECTOR`, and the `DOAL_*_SELECTOR` variables
for the login form) can be changed if DigitalOcean changes the page.

## Commands

Run them via `scripts/run.sh <command>` or, with the venv active, as `do-audit <command>`.

| Command | What it does |
|---|---|
| `login-test [--headed]` | Fresh login without scraping. Prints `LOGIN OK` or `LOGIN FAILED: <reason>`. |
| `check [--headed]` | Verifies the cached session / logs in and opens the audit page. |
| `scrape [--headed]` | Downloads and writes new events. |
| `login` | Fallback: manual login in a window; saves the session (use it when automatic login is blocked, then copy `data/storage_state.json` to the server). |

`--headed` shows the browser window (useful for debugging). **Exit codes:** `0` OK, `2` login/session
failed (set up an alert on this), any other non-zero code = another error (see the log).

**Incremental runs:** the first run downloads the whole history; later runs write only events whose
ID has not been seen yet (`new_events: 0` when nothing is new). To start over, delete **both**
`data/state.json` and `data/audit_logs.ndjson`.

## Output

`data/audit_logs.ndjson`, one event per line, from oldest to newest:

```json
{"event_id":"01M4TG1KT82GZA05YN9H7JASGE","action":"droplet.create","resource_type":"Droplet","resource_id":"608642988","user":"Alice Example","user_email":"alice@example.com","ip_address":"203.0.113.10","timestamp_utc":"2026-10-13T11:23:26Z","scraped_at":"2026-10-14T08:15:00.123456Z","source":"digitalocean_audit"}
```

The file contains names, e-mails and IP addresses; treat it as sensitive data.

## Security

- Protect `.env` (password, TOTP secret) and `data/storage_state.json` (cookies = access to the
  account without a password): mode `600`, owned only by the service user, never in git
  (`.gitignore` excludes them).
- The password and the TOTP secret live on the same server, so 2FA there is effectively
  single-factor. Hence use a dedicated read-only account and a short `DOAL_SESSION_MAX_AGE_*`.
- On a leak, change the password and re-enroll 2FA in DigitalOcean.
- Files in `data/debug/` (screenshots, HTML dumps) can contain e-mails; do not share them.

## Troubleshooting

Always run the scraper as the service user (`sudo -u doaudit …/run.sh`), never as root: a root run
looks for Chromium in `/root/.cache` and may create root-owned files in `data/`.

| Symptom | Cause / solution |
|---|---|
| `Executable doesn't exist at /root/.cache/...` | Started as root. Use `sudo -u doaudit /opt/do-audit/scripts/run.sh …`. |
| `error while loading shared libraries: libglib-2.0.so.0` | Chromium system libraries missing. Re-run `sudo ./scripts/install.sh`. |
| `Permission denied: 'data/scrape.lock'` | `data/` has wrong owner/mode. `sudo chown -R doaudit: /opt/do-audit && sudo chmod 700 /opt/do-audit/data`. |
| `source: not found` (in a `doaudit` shell) | The shell is `sh`. Use `. .venv/bin/activate` or just `scripts/run.sh`. |
| `missing/empty: DOAL_…` | Empty value in `.env`, or `do-audit` was not run from the project root (use `scripts/run.sh`). |
| `DOAL_TOTP_SECRET is not valid base32` | Wrong key. Use the text key under the QR code (A–Z, 2–7), not an app code or a backup code. |
| `2FA code not accepted twice` | Wrong secret or inaccurate system time. |
| `Cloudflare bot challenge…` | Headless mode, or Cloudflare blocks the server IP. Keep `DOAL_HEADLESS=false`; if it persists, run `do-audit login` on a machine with a display and copy `data/storage_state.json` to the server (owner = service user, mode `600`). |
| `Page.goto: Timeout … waiting until "networkidle"` | Busy pages never reach network idle on some servers. Update to the current code, which no longer requires it. |
| Login page shows only a password field | DigitalOcean remembered the last user. Handled automatically: the scraper clicks "Login with a different account", or falls back to the password-only form. |
| `audit table not found on …/dashboard?i=…` | Wrong `DOAL_AUDIT_PATH` for this account type, or the role lacks access. See [Which audit page path?](#which-audit-page-path). |
| `audit table not found` / `no valid GetAuditActions response` (other URL) | The page changed. Look at `data/debug/*.png` and `.html`, then adjust the selectors. |
| `audit_graphql_error` / `next_page_retry` | Temporary error or rate limit; increase `DOAL_PAGE_DELAY_S`. |
| `cannot start Xvfb` | `sudo apt install xvfb` (or re-run `install.sh`). |

## Project layout and development

```
src/do_audit_scraper/
  config.py    settings (DOAL_*)           parser.py   GraphQL response -> AuditEvent
  browser.py   Playwright, login, pages    storage.py  NDJSON + dedup state
  scraper.py   incremental run             cli.py      do-audit commands
  models.py    AuditEvent
scripts/       install.sh (server bootstrap), run.sh (run it), setup.sh (venv + deps + Chromium)
deploy/        systemd service + timer     tests/      pytest
```

```bash
make test        # pytest
make lint        # ruff
```

CI (GitHub Actions) runs `ruff` and `pytest` on every push to `main` and on pull requests.

## Roadmap

- Phase 2: **Wazuh** integration (`localfile` with `log_format json`, decoders and rules).
- Optional: a complementary collector via the official API (`/v2/actions`) with a read-only token.
