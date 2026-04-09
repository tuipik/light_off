#!/usr/bin/env sh
set -eu

headless="${PLAYWRIGHT_HEADLESS:-1}"
xvfb_pid=""

echo "Starting light_off (headless=$headless)"

# Clean stale Chromium profile locks if no chromium process is running
if ! pgrep -f "chrome.*--user-data-dir=/app/pw_profile" >/dev/null 2>&1; then
  rm -f /app/pw_profile/Singleton* /app/pw_profile/lockfile 2>/dev/null || true
fi

cleanup() {
  if [ -n "$xvfb_pid" ] && kill -0 "$xvfb_pid" >/dev/null 2>&1; then
    kill "$xvfb_pid" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

if command -v Xvfb >/dev/null 2>&1; then
  export DISPLAY=:99
  rm -f /tmp/.X99-lock
  Xvfb :99 -screen 0 1280x720x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
  xvfb_pid=$!
  sleep 2

  if kill -0 "$xvfb_pid" >/dev/null 2>&1; then
    echo "Xvfb started on $DISPLAY (pid=$xvfb_pid)"
  else
    echo "Xvfb failed to start, log follows:"
    cat /tmp/xvfb.log || true
    exit 1
  fi
fi

exec python -u main.py
