#!/usr/bin/env bash
# Portable setup: venv + dependencies + Chromium. Works on macOS and Linux.
# Usage: ./scripts/setup.sh [--no-browser]
set -euo pipefail
cd "$(dirname "$0")/.."

PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && \
     "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python >= 3.11 not found. macOS: brew install python@3.12 | Debian/Ubuntu: apt install python3.12 python3.12-venv" >&2
  exit 1
fi
echo "Using $($PY --version) ($PY)"

[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -e ".[dev]"

if [ "${1:-}" != "--no-browser" ]; then
  if [ "$(uname -s)" = "Linux" ] && [ "$(id -u)" = "0" ]; then
    .venv/bin/playwright install --with-deps chromium   # system libs need root
  else
    .venv/bin/playwright install chromium
    [ "$(uname -s)" = "Linux" ] && echo "NOTE: on Linux as non-root, run once: sudo .venv/bin/playwright install-deps chromium"
  fi
fi

if [ "$(uname -s)" = "Linux" ] && ! command -v Xvfb >/dev/null 2>&1; then
  SUDO=""; [ "$(id -u)" != "0" ] && SUDO="sudo"
  echo "Installing Xvfb (virtual display for the headed browser)..."
  $SUDO apt-get install -y xvfb || echo "WARN: install xvfb manually: sudo apt install xvfb"
fi

mkdir -p data
if [ ! -f .env ]; then cp .env.example .env; fi
chmod 600 .env
echo
echo "Done. Next:"
echo "  1) edit .env (DOAL_EMAIL / DOAL_PASSWORD / DOAL_TOTP_SECRET)"
echo "  2) source .venv/bin/activate && do-audit check     # test login (DOAL_HEADLESS=false to watch)"
echo "  3) do-audit scrape"
