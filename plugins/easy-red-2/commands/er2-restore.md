---
description: Put the machine back to normal after Easy Red 2 work — restore the shipping build, destroy any virtual gamepad, clear stale harnesses, and clear the Steam launch options.
allowed-tools: Bash
---

Restore normal state. Do these in order and VERIFY each rather than assuming.

1. **Stop the game**, then restore the shipping build from the mod repo:
   `python3 tools/deploy.py` — then `python3 tools/deploy.py --check`, which must report that
   every deployed file matches. Confirm `DEBUG = false` by grepping the DEPLOYED files, not the
   repo; a sed that missed a trailing comment has silently left diagnostics on before.

2. **Destroy any virtual gamepad**: `echo quit > /tmp/er2pad.fifo`, then confirm
   `/dev/input/js0` is gone. It is visible to every application and can change how the user's
   next game reads input.

3. **Clear stale harnesses**: `pkill -9 -x gamescope-wl`. They carry `--keep-alive`, ignore
   SIGTERM, and make the next launch time out with "harness socket not found".

4. **Clear the Steam launch options** — but FIRST check nothing else is playing:
   ```bash
   python3 -c "import sys;sys.path.insert(0,'${CLAUDE_PLUGIN_ROOT}/tools');import virtual_pad as v;print(v.foreign_steam_games())"
   ```
   **Non-empty means stop.** Closing Steam closes their game. If it is clear, shut Steam down
   gracefully, run `tools/fix_steam_launch_options.py --clear --apply`, restart Steam, and
   **re-verify** — a "cleared" write has failed to stick before when Steam was still running.

Report what you verified, not what you ran.
