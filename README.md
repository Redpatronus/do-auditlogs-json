# DO Audit Scraper

Downloads the **DigitalOcean audit log** (Security → History) and continuously writes it to an
**NDJSON** file (one JSON event per line). It is designed to run on a server and to feed **Wazuh**
(integration is the next phase).

Inspired by [ionsec/DO-Audit-Log-Scraper](https://github.com/ionsec/DO-Audit-Log-Scraper).

## How it works

DigitalOcean has no API for audit logs (an API token is not enough); the data is only available in
the web console. The scraper therefore:

1. starts a browser (Playwright / Chromium) and logs in (e-mail + password + TOTP code),
2. opens `https://cloud.digitalocean.com/security/history`,
3. captures the responses of the `GetAuditActions` GraphQL operation that the page loads by itself
   (exact time, unique ID, action, user, IP) and pages through the results with the "next" button,
4. writes only **new** events (deduplicated by the ID assigned by DigitalOcean).

The logged-in session (cookies) is stored and reused, so it does not log in on every run.

> This is not an official API. If DigitalOcean changes the page or the GraphQL schema, the scraper
> will need to be adjusted. Use it only on your own account and in accordance with DigitalOcean's
> terms.

## Requirements

- Python **3.11+** (macOS: `brew install python@3.12`; Ubuntu: `apt install python3.12 python3.12-venv`)
- A DigitalOcean account that uses e-mail + password login and 2FA via **TOTP** (authenticator app).
  Accounts using Google / GitHub SSO are not supported.
- Linux server: the `xvfb` package (virtual display, installed by `setup.sh`).

Recommendation: create a **dedicated team member** with minimal (read-only) permissions and its own
TOTP secret, rather than using a personal owner account.

## Installation (macOS and Linux)

```bash
./scripts/setup.sh          # finds Python >= 3.11, creates .venv, installs dependencies and Chromium,
                            # on Linux also xvfb, and creates .env (permissions 600)
source .venv/bin/activate
make test                   # optional: run the tests
```

On Linux without root, run `sudo .venv/bin/playwright install-deps chromium` once more after
`setup.sh`.

## Configuration

Everything is configured in the `.env` file (template: `.env.example`), in `KEY=value` format, with
no spaces around `=` and usually without quotes. Values containing special characters (`#`, `$`)
should be wrapped in single quotes: `DOAL_PASSWORD='ab#c$d'`. Never commit the `.env` file.

### Credentials (required)

| Variable | Description |
|---|---|
| `DOAL_EMAIL` | DigitalOcean account e-mail |
| `DOAL_PASSWORD` | password |
| `DOAL_TOTP_SECRET` | the text key shown under the QR code when enabling 2FA (letters A–Z and digits 2–7). A full `otpauth://…` URI is also accepted. **Not** the backup codes. |

You get the TOTP secret when enabling the authenticator app in Account → Security (the "can't scan /
enter manually" option). It is shown only once, so store it. Keep the backup (recovery) codes
separately; the scraper does not need them.

### Other settings

| Variable | Default | Description |
|---|---|---|
| `DOAL_SESSION_MAX_AGE_DAYS` | `7` | After how many days the stored session is discarded and a fresh login is performed. |
| `DOAL_SESSION_MAX_AGE_HOURS` | empty | The same in hours. **Set only one of these two**; when both are empty, 7 days applies. The value should not exceed the session lifetime configured in DigitalOcean. |
| `DOAL_HEADLESS` | `false` | `true` = no window. **Headless is blocked by Cloudflare**, keep `false`. |
| `DOAL_OUTPUT_PATH` | `data/audit_logs.ndjson` | output file |
| `DOAL_STATE_PATH` | `data/state.json` | deduplication state (seen IDs) |
| `DOAL_STORAGE_STATE_PATH` | `data/storage_state.json` | stored session (cookies, **secret**) |
| `DOAL_MAX_PAGES` | `100` | maximum pages per run (1 page = 25 events) |
| `DOAL_PAGE_DELAY_S` | `1.5` | pause between pages; increase on errors (rate limiting) |
| `DOAL_NAV_TIMEOUT_MS` | `45000` | navigation timeout |
| `DOAL_LOG_LEVEL` | `INFO` | log level |
| `DOAL_LOG_JSON` | `true` | logs as JSON (to stderr) |

Selectors (`DOAL_TABLE_SELECTOR`, `DOAL_NEXT_BUTTON_SELECTOR` and the `DOAL_*_SELECTOR` variables for
login) are configurable in case DigitalOcean changes the page.

## Usage

```bash
source .venv/bin/activate

do-audit login-test --headed   # 1. login test only (password + TOTP), the window stays open
do-audit check                 # 2. verifies that the session / audit log page works
do-audit scrape                # 3. downloads new events into data/audit_logs.ndjson
```

| Command | What it does |
|---|---|
| `do-audit login-test [--headed]` | Fresh login without scraping. Prints `LOGIN OK` or `LOGIN FAILED: <reason>`. |
| `do-audit check [--headed]` | Verifies the stored session / logs in and opens the Security History page. |
| `do-audit scrape [--headed]` | Downloads and writes new events. |
| `do-audit login` | Fallback: manual login in a window and session saving (if automatic login fails). |

`--headed` shows the browser window, which is useful for debugging. Shortcuts: `make check`,
`make scrape`.

**Exit codes:** `0` OK, `2` login/session failed (set up an alert on this), any other non-zero
code = another error (details in the log).

### Repeated runs (incremental)

The first run downloads the entire history. Subsequent runs load page 1 and write **only events
whose ID has not been recorded yet**. If page 1 contains one new event and the rest are old, one
event is written. When there is nothing new, the result is `new_events: 0`. Writing happens only
after the run has fully completed, so an error midway does not leave a gap in the data. To start
over, delete **both** `data/state.json` and `data/audit_logs.ndjson`.

## Output

`data/audit_logs.ndjson`, one event per line, from oldest to newest:

```json
{"event_id":"01M4TG1KT82GZA05YN9H7JASGE","action":"droplet.create","resource_type":"Droplet","resource_id":"608642988","user":"Alice Example","user_email":"alice@example.com","ip_address":"203.0.113.10","timestamp_utc":"2026-10-13T11:23:26Z","scraped_at":"2026-10-14T08:15:00.123456Z","source":"digitalocean_audit"}
```

The file contains names, e-mails and IP addresses; treat it as sensitive data.

## Server deployment

**systemd (Ubuntu):**

```bash
sudo useradd -r -m -d /opt/do-audit doaudit
# upload the project to /opt/do-audit, run ./scripts/setup.sh as the doaudit user and edit .env
sudo cp deploy/do-audit.service deploy/do-audit.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now do-audit.timer       # runs every 15 minutes
systemctl list-timers do-audit.timer
journalctl -u do-audit.service -f                # logs
```

The server has no display, so the scraper starts a virtual one (Xvfb) itself and runs a regular,
non-headless Chromium in it. Cloudflare may repeat the challenge for a datacenter IP address, so a
production run must be verified directly on the server.

**Docker:** `docker build -t do-audit .` and then
`docker run --rm --env-file .env -v $PWD/data:/data do-audit scrape`.

## Security

- Protect `.env` (password, TOTP secret) and `data/storage_state.json` (cookies = access to the
  account without a password): permissions `600`, owned only by the service user, never in git.
  `.gitignore` excludes them.
- The password and the TOTP secret live on the same server, so 2FA there is effectively
  single-factor. Hence the dedicated read-only account and a short `DOAL_SESSION_MAX_AGE_*`.
- On a leak, change the password and re-enroll 2FA in DigitalOcean.
- Files in `data/debug/` (screenshots, HTML) may contain e-mails; do not share them.

## Troubleshooting

| Symptom | Cause / solution |
|---|---|
| `missing/empty: DOAL_…` | empty value in `.env`; run `do-audit` from the project root, where `.env` is read from |
| `DOAL_TOTP_SECRET is not valid base32` | wrong key; you need the text key under the QR code (A–Z, 2–7), not the code from the app or a backup code |
| `Cloudflare bot challenge…` | headless mode; set `DOAL_HEADLESS=false` (Xvfb on the server). If you still get the challenge, use `do-audit login` and copy the session over |
| `2FA code not accepted twice` | wrong secret or inaccurate system time |
| `audit_graphql_error` / `next_page_retry` | temporary error or rate limit; increase `DOAL_PAGE_DELAY_S` |
| `audit table not found` / `no valid GetAuditActions response` | the page changed; check `data/debug/*.png` and `.html` and adjust the selectors |
| `cannot start Xvfb` | `sudo apt install xvfb` |

## Project structure

```
src/do_audit_scraper/
  config.py    settings (DOAL_*)           parser.py   GraphQL response → AuditEvent
  browser.py   Playwright, login, pages    storage.py  NDJSON + dedup state
  scraper.py   incremental run             cli.py      do-audit commands
  models.py    AuditEvent
deploy/        systemd service + timer     scripts/    setup.sh
tests/         tests (pytest)              Dockerfile, Makefile, pyproject.toml
```

## Development

```bash
make test        # pytest
make lint        # ruff
```

## Roadmap

- Phase 2: **Wazuh** integration (`localfile` with `log_format json`, decoders and rules).
- Optional: a complementary collector via the official API (`/v2/actions`) with a read-only token.
