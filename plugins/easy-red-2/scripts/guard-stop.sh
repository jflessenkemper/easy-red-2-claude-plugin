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
#
#    ER2_FAKE_HARNESS pins the count so the gate is hermetic. Without it check 13's baseline
#    asserted "clean session -> allow" while a REAL harness happened to be running, and failed for
#    an environmental reason rather than a code one - the same flakiness the AppId pin fixes in
#    guard-bash.sh. A test whose result depends on whether a game is open is not a test.
if [ -n "${ER2_FAKE_HARNESS+set}" ]; then
    stale=${ER2_FAKE_HARNESS:-0}
else
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
fi
if [ "$stale" -gt 0 ] && [ "${ER2_SKIP_HARNESS_CHECK:-0}" != "1" ]; then
    echo "BLOCKED: $stale harness process(es) are still running. They carry --keep-alive and \
IGNORE SIGTERM, and Steam will refuse to start the game while they exist - the next er2_launch \
will time out with 'harness socket not found'. Clear them with er2_stop, which signals only \
processes this plugin launched. NEVER kill gamescope by name - Bazzite Game Mode shares the name. If \
er2_stop leaves one, check it with tools/er2_mcp/launch_record.py owned <pid> before kill <pid>." >&2
    exit 2
fi

# 3. An ORPHANED GAME process. Killing the harness does NOT kill the game it spawned: on
#    2026-09-18 harness 69668 was SIGKILLed, "harness processes remaining: 0" was reported and
#    believed, and game pid 69695 went on running for a day. It then competed with a fresh launch
#    (two Unity instances) and made that launch time out, which got misdiagnosed twice before
#    anyone thought to look for a process that was not a harness.
#
#    Counting only what you went looking for is how that happened; this check looks for the OTHER
#    half. Zombies are excluded for free - a zombie has an empty cmdline so it cannot match the
#    pattern (verified: a zombie gamescope-wl sat unreaped while this guard correctly exited 0).
if [ "${ER2_SKIP_HARNESS_CHECK:-0}" != "1" ]; then
    orphan=0
    for p in /proc/[0-9]*; do
        [ "${p#/proc/}" = "$$" ] && continue
        case "$(head -c 64 "$p/comm" 2>/dev/null)" in
            "Easy Red 2.x86"*) : ;;
            *) continue ;;
        esac
        case "$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null)" in
            *"Easy Red 2"*) orphan=$((orphan + 1)) ;;
        esac
    done
    if [ "$orphan" -gt 0 ]; then
        echo "BLOCKED: $orphan Easy Red 2 game process(es) are still running. SIGKILLing the \
harness leaves the game it spawned alive, and an orphan competes with the next launch until it is \
cleared. Stop it with er2_stop if a harness is attached, otherwise kill the pid directly, then \
re-scan for BOTH names - 'Easy Red 2.x86_64' as well as gamescope-wl/AOE3DEHarness." >&2
        exit 2
    fi
fi

exit 0
