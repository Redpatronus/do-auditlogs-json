#!/bin/bash
# Prints "OK age=<s>" or "STALE ..." for the do-audit heartbeat file; run by Wazuh (command localfile).
# Install: cp do-scraper-check.sh /usr/local/bin/ && chmod 755 /usr/local/bin/do-scraper-check.sh
# MAX must cover 2-3 scraper intervals (the systemd timer runs every 15 minutes).
HB=${DO_HEARTBEAT:-/opt/do-auditlogs-json/data/heartbeat}
MAX=${DO_HEARTBEAT_MAX:-2700}   # 45 minutes

if [ ! -f "$HB" ]; then
  echo "STALE heartbeat_missing"
  exit 0
fi

# GNU stat on Linux, BSD stat on macOS.
MTIME=$(stat -c %Y "$HB" 2>/dev/null || stat -f %m "$HB")
AGE=$(( $(date +%s) - MTIME ))

if [ "$AGE" -gt "$MAX" ]; then
  echo "STALE age=${AGE}s"
else
  echo "OK age=${AGE}s"
fi
