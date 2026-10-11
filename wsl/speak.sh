#!/usr/bin/env bash
# Fire-and-forget local TTS notifier for Claude Code hooks.
# Usage: speak.sh <event-type>   (event-type: "notification" | "stop" | "warm")
# Reads the hook's JSON payload from stdin (may be empty).
#
# Fast path: if the resident tts_server.py daemon is up, hand it the text
# over a Unix socket (near-instant). Slow path: cold-spawn a one-off
# synthesis (10-15s, model load included) and kick off the daemon so the
# *next* call is fast.

set -u
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EVENT="${1:-notification}"
LOG="$DIR/tts.log"
SOCK="${TMPDIR:-/tmp}/claude-tts.sock"

INPUT="$(cat 2>/dev/null || true)"

case "$EVENT" in
  notification)
    MSG="$(printf '%s' "$INPUT" | jq -r '.message // empty' 2>/dev/null)"
    [ -z "$MSG" ] && MSG="Claude needs your attention."
    ;;
  stop)
    PHRASES=(
      "All done!"
      "Finished up!"
      "Ready when you are."
      "Task complete."
      "All set!"
    )
    MSG="${PHRASES[$((RANDOM % ${#PHRASES[@]}))]}"
    ;;
  error)
    TOOL="$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)"
    if [ -n "$TOOL" ]; then
      MSG="$TOOL failed."
    else
      MSG="A tool failed."
    fi

    # Rate-limit: at most one spoken error per COOLDOWN-second window, so a
    # burst of repeated/related failures doesn't get announced N times.
    STATE_DIR="$DIR/state"
    mkdir -p "$STATE_DIR"
    LAST_FILE="$STATE_DIR/last_error_ts"
    COOLDOWN="${CLAUDE_TTS_ERROR_COOLDOWN:-45}"
    NOW=$(date +%s)
    LAST=0
    [ -f "$LAST_FILE" ] && LAST="$(cat "$LAST_FILE" 2>/dev/null || echo 0)"
    if [ $((NOW - LAST)) -ge "$COOLDOWN" ]; then
      echo "$NOW" > "$LAST_FILE"
    else
      echo "$(date '+%F %T') suppressed repeat error within ${COOLDOWN}s cooldown: $MSG" >> "$LOG"
      MSG=""
    fi
    ;;
  precompact)
    PHRASES=(
      "Tidying up my memory for a moment."
      "Compacting context now."
      "Just clearing some headspace."
    )
    MSG="${PHRASES[$((RANDOM % ${#PHRASES[@]}))]}"
    ;;
  subagent_stop)
    PHRASES=(
      "Subagent finished!"
      "A helper task wrapped up."
      "Background task done."
    )
    MSG="${PHRASES[$((RANDOM % ${#PHRASES[@]}))]}"
    ;;
  warm)
    MSG=""
    ;;
  *)
    MSG="Claude notification."
    ;;
esac

start_daemon_if_needed() {
  if ! pgrep -f "$DIR/tts_server.py" >/dev/null 2>&1; then
    # setsid fully detaches from the controlling terminal/session so this
    # survives the invoking wsl.exe call tearing down (which sends SIGHUP
    # to anything still attached to its session -- disown alone doesn't
    # prevent that, only stops bash itself from signaling the job).
    setsid nohup "$DIR/venv/bin/python3" "$DIR/tts_server.py" \
      </dev/null >>"$DIR/tts_server.log" 2>&1 &
    disown
  fi
}

send_via_daemon() {
  python3 - "$SOCK" "$1" <<'PYEOF' 2>>"$LOG"
import socket, sys
sock_path, text = sys.argv[1], sys.argv[2]
try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(2)
    s.connect(sock_path)
    s.sendall((text + "\n").encode("utf-8"))
    s.close()
except OSError:
    sys.exit(1)
PYEOF
}

# Always make sure the daemon is (or will be) running for next time.
start_daemon_if_needed

if [ -n "$MSG" ]; then
  if [ -S "$SOCK" ] && send_via_daemon "$MSG"; then
    : # delivered to the warm daemon
  else
    # Cold fallback: synth directly (slow, ~10-15s) so this event still gets heard.
    setsid nohup "$DIR/venv/bin/python3" "$DIR/speak.py" "$MSG" \
      </dev/null >>"$LOG" 2>&1 &
    disown
  fi
fi

exit 0
