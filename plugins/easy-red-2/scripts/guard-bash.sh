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

# --- Rule 1b: never shut Steam down while somebody else's game is running ------------------------
# `steam -shutdown` is GRACEFUL, so Rule 1 above does not catch it -- and Rule 1's own message
# actively recommends it. But it still closes every running Steam game. On 2026-09-13 this killed
# the user's Bannerlord mid-session: the operator ran the foreign-AppId check, PRINTED the result,
# and then shut Steam down anyway without gating on it. The user had already asked twice not to
# have their games closed. A check whose result is advisory is not a check.
if printf '%s' "$cmd" | grep -qiE 'steam([.]sh)?[[:space:]]+(-{1,2})shutdown'; then
    # Test seam: the gate must be able to prove it blocks without a real game running.
    # NOTE the ${VAR+set} form, NOT ${VAR:-}. An EMPTY value is a meaningful case here
    # ("no games running"), and ${VAR:-} cannot tell empty from unset -- that exact
    # confusion made the first version of this gate block the allow cases.
    if [ -n "${ER2_FAKE_APPIDS+set}" ]; then
        raw=$(printf '%s' "$ER2_FAKE_APPIDS" | tr ',' '\n')
    else
        raw=$(for p in /proc/[0-9]*; do
            [ "${p#/proc/}" = "$$" ] && continue
            tr '\0' ' ' < "$p/cmdline" 2>/dev/null \
                | grep -oE 'SteamLaunch AppId=[0-9]+' | grep -oE '[0-9]+$'
        done 2>/dev/null)
    fi
    # Easy Red 2 itself never counts: closing it is part of the normal workflow.
    foreign=$(printf '%s' "$raw" | grep -E '^[0-9]+$' | sort -u | grep -v '^1324780$' | tr '\n' ' ')
    if [ -n "$(printf '%s' "$foreign" | tr -d '[:space:]')" ]; then
        echo "BLOCKED: Steam game(s) running with AppId $foreign. 'steam -shutdown' is graceful but \
still closes EVERY running Steam game. This killed the user's Bannerlord on 2026-09-13 and their \
Hell Let Loose session was nearly lost the same way; they have asked more than once not to have \
games closed. WAIT until they finish, or ask. Easy Red 2 (1324780) does not count - closing that \
one is part of the normal launch-option workflow." >&2
        exit 2
    fi
fi

# --- Rule 1c: never LAUNCH Easy Red 2 while someone else's game is running -----------------------
# On 2026-09-13 this was done deliberately, reasoning that direct mode (via_steam:false) avoids
# restarting Steam and is therefore safe alongside another game. It is not. Without DLC
# entitlement Steam pushes a DLC STORE PAGE through the overlay, the Steam overlay is shared
# process-wide, and it attached to the user's foreground game -- an IRONMAN Bannerlord save --
# leaving a Vulkan-layer input grab that survived killing gameoverlayui. They had to restart.
# Steam mode is no better: it needs launch options, which needs Steam shut down, which closes
# their game. There is no safe mode; the only safe action is to wait.
if printf '%s' "$cmd" | grep -qiE '(er2(_| )launch|bin/er2[[:space:]]+launch)'; then
    foreign=$(for p in /proc/[0-9]*; do
        [ "${p#/proc/}" = "$$" ] && continue
        tr '\0' ' ' < "$p/cmdline" 2>/dev/null \
            | grep -oE 'SteamLaunch AppId=[0-9]+' | grep -oE '[0-9]+$'
    done 2>/dev/null | sort -u | grep -v '^1324780$' | tr '\n' ' ')
    [ -n "${ER2_FAKE_APPIDS+set}" ] && foreign=$(printf '%s' "$ER2_FAKE_APPIDS" | tr ',' ' ' \
        | tr ' ' '\n' | grep -E '^[0-9]+$' | grep -v '^1324780$' | tr '\n' ' ')
    if [ -n "$(printf '%s' "$foreign" | tr -d '[:space:]')" ]; then
        echo "BLOCKED: Steam game(s) running with AppId $foreign. Do NOT launch Easy Red 2 now. \
Direct mode makes Steam push a DLC store page through the SHARED overlay, which attaches to the \
game they are playing and can leave an input grab that outlives the overlay process - this made \
an Ironman Bannerlord save unplayable. Steam mode is worse: it needs launch options, which needs \
Steam closed, which ends their session. WAIT until they are finished, or ask." >&2
        exit 2
    fi
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
