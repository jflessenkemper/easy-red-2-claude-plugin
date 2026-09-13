---
description: Report Easy Red 2 harness, Steam and leftover state — is the harness up, is another game running, is a diagnostic build deployed, is a virtual gamepad still live.
allowed-tools: Bash
---

Report the current state, as values rather than impressions. Run these and show the results:

```bash
P="${CLAUDE_PLUGIN_ROOT}/tools"
echo "harness socket : $(ls ~/.er2harness.sock 2>/dev/null || echo ABSENT)"
echo "steam          : $(pidof steam || echo down)"
echo "other games    : $(python3 -c "import sys;sys.path.insert(0,'$P');import virtual_pad as v;print(v.foreign_steam_games() or 'none')")"
echo "virtual pad    : $(ls /dev/input/js0 2>/dev/null || echo none)"
R="$HOME/.config/unity3d/Corvostudio/Easy Red 2/mission_editor"
[ -d "$R" ] && grep -rhE '^local (DEBUG|VERBOSE) = true' "$R" | sort -u | sed 's/^/diagnostic!   : /'
n=0; for p in /proc/[0-9]*; do c=$(cat $p/comm 2>/dev/null); case "$c" in gamescope-wl|AOE3DEHarness)
  case "$(tr '\0' ' ' < $p/cmdline 2>/dev/null)" in *AOE3DEHarness*) n=$((n+1));; esac;; esac; done
echo "harness procs  : $n"
```

Then say plainly whether it is safe to touch Steam right now. **If "other games" is non-empty it
is NOT safe** — a graceful `steam -shutdown` still closes every running Steam game, and that has
already cost the user a session mid-match.
