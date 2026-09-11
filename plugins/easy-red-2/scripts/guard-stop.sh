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
[ -d "$ME" ] || exit 0     # nothing deployed anywhere; nothing to police

dirty=""
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

if [ -n "$dirty" ]; then
    echo "BLOCKED: a DIAGNOSTIC build is still deployed. Restore the shipping build before \
finishing - run tools/deploy.py in the er2-realistic repo, then verify the flags BY GREP rather \
than from memory (a sed that missed a trailing comment has silently left diagnostics on before). \
Diagnostic files:$dirty" >&2
    exit 2
fi
exit 0
