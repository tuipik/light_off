#!/usr/bin/env sh
set -eu

headless="${PLAYWRIGHT_HEADLESS:-1}"

echo "Starting light_off (headless=$headless)"

# Clean stale Chromium profile locks if no chromium process is running
if ! pgrep -f "chrome.*--user-data-dir=/app/pw_profile" >/dev/null 2>&1; then
  rm -f /app/pw_profile/Singleton* /app/pw_profile/lockfile 2>/dev/null || true
fi

if command -v xvfb-run >/dev/null 2>&1; then
  echo "Starting under xvfb-run"
  exec xvfb-run -a --server-args="-screen 0 1280x720x24 -nolisten tcp" python -u main.py
fi

echo "xvfb-run not found, starting without virtual display"
exec python -u main.py
