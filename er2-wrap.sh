#!/usr/bin/env bash
# er2-wrap.sh - Steam Launch Options wrapper for Easy Red 2.
#
#   Launch Options (paste once, while Steam is closed or via the Properties dialog):
#       /var/home/jflessenkemper/er2-plugin/er2-wrap.sh %command%
#
# NORMAL PLAY: no flag file -> `exec "$@"`. The game starts exactly as Steam built it; this
# script is gone from the process tree (exec), so nothing about Jordan's play changes.
#
# HARNESS MODE: only when ALL of these hold
#   * flag file $ER2_FLAG (default ~/.er2harness.enabled) exists,
#   * it is younger than ER2_FLAG_MAX_AGE_S (default 1800 s) - a flag left behind by a crashed
#     run must never hijack a later real play session into an invisible headless compositor,
#   * Steam says this is AppId 1324780 (SteamAppId / SteamGameId / "AppId=" in the argv),
# the game is run under the AOE3DEHarness gamescope with control socket ~/.er2harness.sock and
# this process's PID is written to the plugin's launch record BEFORE exec (exec keeps the pid
# and its /proc start time, so the recorded entry IS the harness), which is what lets er2_stop
# kill it and never Game Mode's gamescope.
#
# Steam hands %command% over as separate argv words (reaper SteamLaunch AppId=N -- ...game);
# we never re-split or re-quote them: "$@" is passed through verbatim.
#
# ER2_WRAP_DRY_RUN=1 prints the decision and the command instead of exec'ing (tests use this).
set -u

APPID=1324780
HOME_DIR=${HOME:-/var/home/jflessenkemper}
FLAG=${ER2_FLAG:-$HOME_DIR/.er2harness.enabled}
MAX_AGE=${ER2_FLAG_MAX_AGE_S:-1800}
SOCK=${ER2_HARNESS_SOCK:-$HOME_DIR/.er2harness.sock}
HARNESS=${ER2_HARNESS_BIN:-$HOME_DIR/AOE-3-DE-Harness/build-f44/src/AOE3DEHarness}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RECORD=${ER2_LAUNCH_RECORD:-$HERE/plugins/easy-red-2/tools/er2_mcp/launch_record.py}
LOG=${ER2_WRAP_LOG:-/tmp/er2_mcp/er2-wrap.log}

run() {
  if [ "${ER2_WRAP_DRY_RUN:-0}" = 1 ]; then
    printf 'DRYRUN'; printf ' [%s]' "$@"; printf '\n'; exit 0
  fi
  exec "$@"
}

log() { mkdir -p "$(dirname "$LOG")" 2>/dev/null && printf '%s %s\n' "$(date '+%F %T')" "$*" >>"$LOG" 2>/dev/null; }

[ "$#" -gt 0 ] || { echo "er2-wrap.sh: no command given (Launch Options must end in %command%)" >&2; exit 64; }


is_er2() {
  [ "${SteamAppId:-}" = "$APPID" ] || [ "${SteamGameId:-}" = "$APPID" ] && return 0
  local a; for a in "$@"; do [ "$a" = "AppId=$APPID" ] && return 0; done
  return 1
}

if [ ! -e "$FLAG" ]; then
  log "passthrough: no flag"; run "$@"
fi
now=$(date +%s); mt=$(stat -c %Y "$FLAG" 2>/dev/null || echo 0)
if [ $((now - mt)) -gt "$MAX_AGE" ]; then
  log "passthrough: flag is $((now - mt))s old (> $MAX_AGE), ignoring stale flag"; run "$@"
fi
if ! is_er2 "$@"; then
  log "passthrough: not AppId $APPID"; run "$@"
fi
if [ ! -x "$HARNESS" ]; then
  log "passthrough: harness binary missing: $HARNESS"; run "$@"
fi

# stale socket: a leftover path with no listener makes the harness bind fail. The orchestrator
# already cleaned it; only remove it here if nothing answers on it.
if [ -S "$SOCK" ] && command -v python3 >/dev/null; then
  python3 - "$SOCK" <<'PY' && rm -f "$SOCK"
import socket, sys
s = socket.socket(socket.AF_UNIX)
s.settimeout(1)
try:
    s.connect(sys.argv[1]); sys.exit(1)      # live: keep
except (ConnectionRefusedError, FileNotFoundError):
    sys.exit(0)                               # stale: remove
except OSError:
    sys.exit(1)
PY
fi

# Record OUR pid before exec: exec keeps pid + start time, so this entry is the harness itself.
if [ "${ER2_WRAP_DRY_RUN:-0}" != 1 ]; then
  python3 "$RECORD" record "$$" 2>/dev/null || log "warning: could not record pid $$"
fi
log "harness: pid $$ sock $SOCK"
# Flags mirror tools/fix_steam_launch_options.py FLAGS (check.sh keeps them in sync).
run "$HARNESS" --keep-alive -W 1920 -H 1080 -w 1920 -h 1080 -r 60 --framerate-limit 60 \
  --force-grab-cursor --backend headless --xwayland-count 1 --harness-socket "$SOCK" -- "$@"
