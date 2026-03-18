#!/usr/bin/env sh
set -eu

headless="${PLAYWRIGHT_HEADLESS:-1}"

echo "Starting light_off (headless=$headless)"

# Clean stale Chromium profile locks if no chromium process is running
if ! pgrep -f "chrome.*--user-data-dir=/app/pw_profile" >/dev/null 2>&1; then
  rm -f /app/pw_profile/Singleton* /app/pw_profile/lockfile 2>/dev/null || true
fi

if [ -z "${DISPLAY:-}" ] && command -v Xvfb >/dev/null 2>&1; then
  export DISPLAY=:99
  Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
  echo "Xvfb started on $DISPLAY"
fi

exec python -u main.py
