#!/usr/bin/env bash
# PreToolUse guard for Bash. Turns two rules that were only ever COMMENTS into enforcement.
#
# Both of these have actually happened on this project, in the same session:
#   * `pkill -9 steam` destroyed the Steam login session, which blocked the whole task and left
#     the user to re-authenticate. A graceful `steam -shutdown` was already in progress; the
#     escalation is what did the damage.
#   * a mute loop over every sink-input silenced the user's OTHER game AND a live voice call.
#     Only the game's own FMOD sink-input may be touched, and only by MOVING it to the null sink.
#
# The docs are explicit that this is the difference that matters: an instruction in CLAUDE.md
# "is a request, not a guarantee. A PreToolUse hook that blocks the edit is enforcement."
#
# Contract: stdin is the hook JSON; exit 2 blocks the call and stderr becomes the reason Claude
# sees. Exit 0 allows. We deliberately do NOT use the JSON permissionDecision form here because
# exit 2 + stderr is the simpler surface and carries the reason just as well.
set -uo pipefail

payload=$(cat)

# jq is not guaranteed present; fall back to python3, which is (the MCP server needs it).
if command -v jq >/dev/null 2>&1; then
    cmd=$(printf '%s' "$payload" | jq -r '.tool_input.command // ""')
else
    cmd=$(printf '%s' "$payload" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("tool_input",{}).get("command",""))
except Exception: print("")')
fi

[ -z "$cmd" ] && exit 0

# --- Rule 1: never force-kill Steam -------------------------------------------------------------
# Matches kill -9 / -KILL / -SIGKILL and killall aimed at steam, in any order of flags.
if printf '%s' "$cmd" | grep -qiE '(pkill|kill|killall)([[:space:]]+-[^[:space:]]+)*[[:space:]]+(-9|-KILL|-SIGKILL)' \
   && printf '%s' "$cmd" | grep -qi 'steam'; then
    echo "BLOCKED: never force-kill Steam. On 2026-09-08 a pkill -9 destroyed the Steam login \
session, which blocked the entire task and forced the user to sign in again - and a graceful \
shutdown was already in progress at the time. Run 'steam -shutdown' and WAIT at least 2 minutes. \
If Steam still has not exited, abandon whatever needed Steam closed and report it as blocked. \
Never escalate the signal." >&2
    exit 2
fi
if printf '%s' "$cmd" | grep -qiE '\bkillall[[:space:]]+([-][^[:space:]]+[[:space:]]+)*steam\b'; then
    echo "BLOCKED: killall against Steam is a force-kill by another name. Use 'steam -shutdown' \
and wait; never escalate." >&2
    exit 2
fi

# --- Rule 2: never mute the default sink, and never sweep all sink-inputs ------------------------
if printf '%s' "$cmd" | grep -qE 'pactl[^|;&]*set-sink-mute[^|;&]*@DEFAULT_SINK@'; then
    echo "BLOCKED: do not mute @DEFAULT_SINK@. Doing this once silenced the user's other game AND \
a live voice call. Isolate the GAME only: create the er2_silence null sink and MOVE the game's own \
sink-input to it (pactl move-sink-input <index> er2_silence), selecting only inputs whose \
application.name starts with FMOD. Note PULSE_SINK alone is not sufficient - module-stream-restore \
re-routes the stream after creation, so move it after launch and verify." >&2
    exit 2
fi
# a loop/xargs that mutes every sink-input
if printf '%s' "$cmd" | grep -qE 'set-sink-input-mute' \
   && printf '%s' "$cmd" | grep -qE '(for[[:space:]]|while[[:space:]]|xargs|\$\(pactl[^)]*list[^)]*short[^)]*sink-inputs)'; then
    echo "BLOCKED: this looks like it mutes EVERY sink-input. That muted the user's other game and \
a live voice call. Target only the game's own FMOD sink-input, and prefer moving it to the \
er2_silence null sink over muting." >&2
    exit 2
fi

exit 0
