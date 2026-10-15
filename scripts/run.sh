#!/usr/bin/env bash
# Run the scraper. Cron/systemd friendly: works from any directory, no environment to prepare
# (everything is set up once by scripts/install.sh on Linux or scripts/setup.sh elsewhere).
# Usage: scripts/run.sh [do-audit arguments]      default: scrape
# Exit code is the one of do-audit (2 = login/session failed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BIN="$ROOT/.venv/bin/do-audit"

[ -x "$BIN" ] || { echo "not installed: run scripts/install.sh first" >&2; exit 1; }
[ -f .env ] || { echo "$ROOT/.env is missing (copy .env.example and fill it in)" >&2; exit 1; }

# When started as root (e.g. root's crontab), run as the project owner so that no root-owned files
# appear in data/ and Chromium is found in the owner's home.
if [ "$(id -u)" = "0" ]; then
  OWNER="$(stat -c %U "$ROOT")"
  if [ "$OWNER" != "root" ]; then
    exec runuser -u "$OWNER" -- env HOME="$(getent passwd "$OWNER" | cut -d: -f6)" \
      "$BIN" "${@:-scrape}"
  fi
fi
exec "$BIN" "${@:-scrape}"
