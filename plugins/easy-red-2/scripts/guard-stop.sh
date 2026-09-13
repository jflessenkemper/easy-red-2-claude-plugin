#!/usr/bin/env bash
# Stop guard: refuse to end the session with a DIAGNOSTIC build deployed.
#
# "Never leave a diagnostic build deployed" has been a comment for the life of this project, and
# restoring it has always been a manual chore that only works if it is remembered. A diagnostic
# build left in place means the user's next play session runs with DEBUG logging on: ~1.1 KB plus
# a stack walk per line, which is a real framerate cost and a 50MB+ Player.log.
#
# Stop CAN block; the reason is returned to Claude and the conversation continues, so this is an
# instruction to go fix it rather than a dead end.
set -uo pipefail

CFG="${ER2_CFG_DIR:-$HOME/.config/unity3d/Corvostudio/Easy Red 2}"
ME="$CFG/mission_editor"

# NOTE: "no missions deployed" used to `exit 0` right here, which skipped the leftover checks
# further down as well. That was wrong: a live virtual gamepad and stale harness processes
# outlive the session and affect the user's OTHER games whether or not this project has anything
# deployed. Only the BUILD scan is conditional on the directory existing.
dirty=""
if [ -d "$ME" ]; then
while IFS= read -r f; do
    # a shipping build has `local DEBUG = false`; anything true is diagnostic
    if grep -qE '^local (DEBUG|VERBOSE|WATCH|TELEMETRY|TRACE_LOOP)[[:space:]]*=[[:space:]]*true' "$f" 2>/dev/null; then
        dirty="$dirty
  ${f#$ME/}"
    fi
    # A per-soldier sample of 1 is diagnostic in a real battle - it is what makes the log enormous.
    # BUT IT IS THE INTENDED STATE ON THE DEMONSTRATION RANGE, which exists to be measured: at the
    # shipping default of 6 an 11-round run yielded 41 state lines across 13 stations and could not
    # verify anything. So the test map is exempt for DBG_SAMPLE only. DEBUG and friends are still
    # refused everywhere, including there.
    #
    # Narrowed deliberately: this guard fired on the test map's intended build, and a guard that
    # cries wolf on a correct state is one you learn to ignore - which is worse than not having it.
    case "$f" in
        *"ME_Realistic Test map"*) : ;;
        *)
            if grep -qE '^local DBG_SAMPLE[[:space:]]*=[[:space:]]*1[[:space:]]*($|--)' "$f" 2>/dev/null; then
                dirty="$dirty
  ${f#$ME/}  (DBG_SAMPLE = 1)"
            fi
            ;;
    esac
done < <(find "$ME" -type f -name '*.lua' 2>/dev/null)
fi

if [ -n "$dirty" ]; then
    echo "BLOCKED: a DIAGNOSTIC build is still deployed. Restore the shipping build before \
finishing - run tools/deploy.py in the er2-realistic repo, then verify the flags BY GREP rather \
than from memory (a sed that missed a trailing comment has silently left diagnostics on before). \
Diagnostic files:$dirty" >&2
    exit 2
fi

# --- Leftovers that outlive the session and affect the user's OTHER games ---------------------
# Both of these actually happened. They are invisible from inside the conversation, which is
# exactly why a Stop guard is the right place to catch them.

# 1. A virtual gamepad created via /dev/uinput is GLOBALLY visible. Left alive it can flip the
#    user's next game to controller prompts, and nothing in the transcript would hint at why.
if [ -e /dev/input/js0 ] && [ "${ER2_SKIP_PAD_CHECK:-0}" != "1" ]; then
    if grep -qs 'ER2 Virtual Pad' /sys/class/input/js0/device/name 2>/dev/null; then
        echo "BLOCKED: the ER2 virtual gamepad is still live at /dev/input/js0. It is visible to \
EVERY application, so leaving it can change how the user's next game reads input. Destroy it \
(echo quit > the daemon FIFO, or stop virtual_pad.py) and confirm /dev/input/js0 is gone." >&2
        exit 2
    fi
fi

# 2. Stale --keep-alive harness instances ignore SIGTERM and silently block the NEXT launch:
#    Steam believes the game is already running, so er2_launch times out with no socket. This
#    cost a full diagnostic detour once before the cause was found.
#    Matching on cmdline ALONE is wrong: any shell command that merely mentions the harness --
#    including the one testing this guard -- has the string in its own /proc cmdline and gets
#    counted. Excluding $$ is not enough, because the offender is usually the PARENT shell. So
#    require the process NAME to be the harness too; a shell can carry the text but never the
#    comm. This is the same self-match trap that makes pgrep -f unusable here.
stale=0
for p in /proc/[0-9]*; do
    [ "${p#/proc/}" = "$$" ] && continue
    comm=$(cat "$p/comm" 2>/dev/null) || continue
    case "$comm" in
        gamescope-wl|AOE3DEHarness) : ;;
        *) continue ;;
    esac
    case "$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null)" in
        *AOE3DEHarness*) stale=$((stale + 1)) ;;
    esac
done
if [ "$stale" -gt 0 ] && [ "${ER2_SKIP_HARNESS_CHECK:-0}" != "1" ]; then
    echo "BLOCKED: $stale harness process(es) are still running. They carry --keep-alive and \
IGNORE SIGTERM, and Steam will refuse to start the game while they exist - the next er2_launch \
will time out with 'harness socket not found'. Clear them with: pkill -9 -x gamescope-wl \
(pgrep/pkill -f are blocked here; they match the calling shell)." >&2
    exit 2
fi

exit 0
