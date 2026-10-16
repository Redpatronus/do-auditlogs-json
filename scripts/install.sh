#!/usr/bin/env bash
# One-shot server bootstrap (Debian/Ubuntu, run as root). Prepares everything:
# system packages, service user, venv, Python deps, Chromium + its system libraries, .env.
# Idempotent: safe to re-run (new server, or after updating the code).
# Usage: sudo ./scripts/install.sh [--user NAME] [--systemd]
#   --user NAME   service user that owns the project and runs the scraper (default: doaudit)
#   --systemd     also install and enable the systemd timer (every 15 minutes)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER="doaudit"
SYSTEMD=0
while [ $# -gt 0 ]; do
  case "$1" in
    --user) APP_USER="${2:?--user needs a name}"; shift 2 ;;
    --systemd) SYSTEMD=1; shift ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

[ "$(uname -s)" = "Linux" ] || { echo "Linux only; on macOS use ./scripts/setup.sh" >&2; exit 1; }
[ "$(id -u)" = "0" ] || { echo "Run as root: sudo $0" >&2; exit 1; }
command -v apt-get >/dev/null || { echo "apt-get not found (Debian/Ubuntu only)" >&2; exit 1; }

py_ok() {
  for c in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && \
       "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then return 0; fi
  done
  return 1
}

echo "==> System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl xvfb python3 python3-venv python3-pip
if ! py_ok; then
  apt-get install -y -qq python3.12 python3.12-venv \
    || apt-get install -y -qq python3.11 python3.11-venv || true
fi
py_ok || { echo "Python >= 3.11 is not available from apt on this system; install it first" >&2; exit 1; }

echo "==> Service user '$APP_USER'"
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd -r -M -d "$ROOT" -s /bin/bash "$APP_USER"
fi
chown -R "$APP_USER": "$ROOT"

echo "==> venv, Python dependencies, Chromium (as $APP_USER)"
runuser -l "$APP_USER" -c "cd $(printf %q "$ROOT") && ./scripts/setup.sh"

echo "==> Chromium system libraries (as root)"
"$ROOT/.venv/bin/playwright" install-deps chromium

chmod 700 "$ROOT/data"
chmod 600 "$ROOT/.env"
chown -R "$APP_USER": "$ROOT"

if [ "$SYSTEMD" = "1" ]; then
  echo "==> systemd timer"
  for f in do-audit.service do-audit.timer; do
    sed -e "s#/opt/do-auditlogs-json#$ROOT#g" -e "s#^User=.*#User=$APP_USER#" \
      "$ROOT/deploy/$f" > "/etc/systemd/system/$f"
  done
  systemctl daemon-reload
  systemctl enable --now do-audit.timer
fi

cat <<EOF

Done. Remaining steps:
  1) edit $ROOT/.env: DOAL_EMAIL, DOAL_PASSWORD, DOAL_TOTP_SECRET and DOAL_AUDIT_PATH
  2) test:  sudo -u $APP_USER $ROOT/scripts/run.sh login-test
            sudo -u $APP_USER $ROOT/scripts/run.sh scrape
  3) schedule (pick one):
       cron:     sudo crontab -u $APP_USER -e   and add
                 */15 * * * * $ROOT/scripts/run.sh >> $ROOT/data/run.log 2>&1
       systemd:  sudo $ROOT/scripts/install.sh --user $APP_USER --systemd
EOF
