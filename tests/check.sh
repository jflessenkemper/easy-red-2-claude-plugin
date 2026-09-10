#!/usr/bin/env bash
# Static release checks for the Easy Red 2 Claude plugin. No game required.
#
# Every check here corresponds to a defect that actually shipped: a name referenced but never
# imported (py_compile does not catch it), a tool advertised in the schema but not implemented,
# and error text that pointed at a path which did not exist.
#
# Usage:  tests/check.sh          (exit 0 = all pass)
set -uo pipefail
cd "$(dirname "$0")/.."

PASS=0; FAIL=0
ok()  { printf '  \033[32mPASS\033[0m  %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); }

SERVER=plugins/easy-red-2/tools/er2_mcp/server.py
PY_FILES="$SERVER tools/analyse_run.py tools/fix_steam_launch_options.py"

echo "== 1. Python syntax =="
for f in $PY_FILES; do
  [ -f "$f" ] || continue
  if python3 -m py_compile "$f" 2>/dev/null; then ok "$f compiles"; else bad "$f FAILS to compile"; fi
done

echo "== 2. No name referenced but never defined or imported =="
# py_compile cannot see this - name lookup is a RUNTIME operation, so a module full of undefined
# references compiles fine and then raises NameError in front of the user, mid-task.
python3 tests/undefined_names.py $PY_FILES
[ $? -eq 0 ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1))

echo "== 3. Every advertised tool has an implementation =="
python3 - "$SERVER" <<'PY'
import re, sys
src = open(sys.argv[1]).read()
advertised = set(re.findall(r'"(er2_[a-z_]+)"\s*:', src))
implemented = {m[2:] for m in re.findall(r'def (t_[a-z_]+)\(', src)}
implemented = {"er2_" + n for n in implemented}
missing = sorted(advertised - implemented)
orphan = sorted(implemented - advertised)
if missing:
    print("  \033[31mFAIL\033[0m  advertised but not implemented: %s" % ", ".join(missing))
elif orphan:
    print("  \033[33mWARN\033[0m  implemented but not advertised: %s" % ", ".join(orphan))
    print("  \033[32mPASS\033[0m  every advertised tool is implemented")
else:
    print("  \033[32mPASS\033[0m  every advertised tool is implemented")
sys.exit(1 if missing else 0)
PY
[ $? -eq 0 ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1))

echo "== 4. Paths quoted in error text actually exist =="
# An error message that names a fix script is worthless if the path is wrong. PLUGIN_ROOT is
# computed by walking up from server.py, so a directory move silently breaks every such message.
python3 - "$SERVER" <<'PY'
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("er2s", sys.argv[1])
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass
except Exception as e:
    print("  \033[31mFAIL\033[0m  server.py does not import cleanly: %s" % e); sys.exit(1)
root = getattr(m, "PLUGIN_ROOT", None)
if not root or not os.path.isdir(root):
    print("  \033[31mFAIL\033[0m  PLUGIN_ROOT does not resolve to a directory: %r" % root); sys.exit(1)
tool = os.path.join(root, "tools/fix_steam_launch_options.py")
if not os.path.exists(tool):
    print("  \033[31mFAIL\033[0m  error text points at a missing script: %s" % tool); sys.exit(1)
print("  \033[32mPASS\033[0m  PLUGIN_ROOT resolves and the referenced tools exist")
PY
[ $? -eq 0 ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1))

echo "== 5. Plugin manifest is present and valid =="
for f in plugins/easy-red-2/.claude-plugin/plugin.json plugins/easy-red-2/.mcp.json; do
  if [ -f "$f" ] && python3 -c "import json,sys;json.load(open('$f'))" 2>/dev/null; then
    ok "$(basename $f) is valid JSON"
  else
    bad "$f missing or invalid JSON"
  fi
done

echo "== 6. plugin.json version matches the newest CHANGELOG entry =="
# These drifted once already: 1.1.0 was written up in the CHANGELOG and tagged, while
# plugin.json still advertised 1.0.0. Nothing failed, so nobody noticed - the manifest version
# is what a user actually installs and sees, so a stale one misreports which build they have.
python3 - <<'PY'
import json, re, sys
man = json.load(open("plugins/easy-red-2/.claude-plugin/plugin.json")).get("version")
m = re.search(r'^## \[([0-9]+\.[0-9]+\.[0-9]+)\]', open("CHANGELOG.md").read(), re.M)
top = m.group(1) if m else None
if man != top:
    print("  \033[31mFAIL\033[0m  plugin.json=%s but newest CHANGELOG entry=%s" % (man, top))
    sys.exit(1)
print("  \033[32mPASS\033[0m  plugin.json and CHANGELOG agree on %s" % man)
PY
[ $? -eq 0 ] && PASS=$((PASS+1)) || FAIL=$((FAIL+1))

echo "== 10. The harness socket path agrees across all three sources =="
# THREE places name this socket and they had DRIFTED into two different values:
#   server.py           ~/.er2harness.sock   (correct - the MCP server listens here)
#   fix_steam_launch..  ~/.er2harness.sock   (correct - written into the Steam launch options)
#   .mcp.json           /tmp/ER2Harness.sock (WRONG - and it OVERRIDES the server default)
#   that tool's printed "Control socket:" line  /tmp/ER2Harness.sock (WRONG, hardcoded)
# Because .mcp.json's env wins, an INSTALLED plugin pointed its MCP server at a socket the
# harness never creates, so every tool would fail with "harness socket not found" and the
# via_steam path could never connect. Nothing in the code errors - the paths just never meet.
python3 - <<'PY2'
import json, re, sys

mcp = json.load(open("plugins/easy-red-2/.mcp.json"))
env = mcp["mcpServers"]["easy-red-2"].get("env", {})
mcp_sock = env.get("ER2_HARNESS_SOCK", "")

srv = open("plugins/easy-red-2/tools/er2_mcp/server.py").read()
m = re.search(r'SOCK\s*=\s*os\.environ\.get\("ER2_HARNESS_SOCK"\)\s*or\s*os\.path\.join\(HOME,\s*"([^"]+)"\)', srv)
srv_sock = m.group(1) if m else None

fx = open("tools/fix_steam_launch_options.py").read()
m2 = re.search(r'^SOCKET\s*=\s*os\.path\.join\(HOME,\s*"([^"]+)"\)', fx, re.M)
fx_sock = m2.group(1) if m2 else None

fail = []
if srv_sock is None:
    fail.append("could not parse SOCK out of server.py")
if fx_sock is None:
    fail.append("could not parse SOCKET out of fix_steam_launch_options.py")
if srv_sock and fx_sock and srv_sock != fx_sock:
    fail.append("server.py uses ~/%s but fix_steam_launch_options.py writes ~/%s into the launch "
                "options - the harness would listen where the server is not looking"
                % (srv_sock, fx_sock))
# .mcp.json may leave it unset, or default it to the SAME path; it must never name a different one.
if srv_sock and mcp_sock and srv_sock not in mcp_sock:
    fail.append(".mcp.json defaults ER2_HARNESS_SOCK to %r, which does not contain the server's "
                "own path %r. This env value OVERRIDES the server default, so an installed plugin "
                "would look for a socket the harness never creates." % (mcp_sock, srv_sock))
# the printed hint must be derived, not hardcoded to some other path
if re.search(r'Control socket: */tmp/', fx) or '"/tmp/ER2Harness.sock")' in fx:
    fail.append("fix_steam_launch_options.py still hardcodes a /tmp control-socket path in its "
                "output instead of printing SOCKET")

if fail:
    for f in fail:
        print("FAIL  " + f)
    sys.exit(1)
print("ok    socket path consistent across server.py, .mcp.json and the launch-options writer")
PY2
if [ $? -eq 0 ]; then ok "harness socket path agrees everywhere"; else bad "harness socket path disagrees between sources"; fi

echo "== 11. Every doc path the MCP tools cite is actually SHIPPED in the plugin =="
# er2_play_mission's description told the reader to consult docs/ui-map.md THREE times, while that
# file existed only at REPO root - outside plugins/easy-red-2/. An installed plugin therefore
# pointed users at a file they did not have. Nothing errors; the advice is just dead.
python3 - <<'PY2'
import os, re, sys
ROOT = "plugins/easy-red-2"
src = open(os.path.join(ROOT, "tools/er2_mcp/server.py")).read()
# only paths that look plugin-relative, e.g. docs/ui-map.md
cited = sorted(set(re.findall(r'\b(docs/[A-Za-z0-9_.-]+\.md)\b', src)))
missing = [c for c in cited if not os.path.exists(os.path.join(ROOT, c))]
if not cited:
    print("ok    no plugin-relative doc paths cited by the tools")
    sys.exit(0)
if missing:
    for m in missing:
        print("FAIL  the tools cite %r but %s/%s does not exist - an installed plugin would point "
              "the user at a file it does not ship" % (m, ROOT, m))
    sys.exit(1)
print("ok    all %d cited doc path(s) ship inside the plugin: %s" % (len(cited), ", ".join(cited)))
PY2
if [ $? -eq 0 ]; then ok "cited doc paths are shipped"; else bad "the plugin cites a doc it does not ship"; fi

echo "== 12. The guard hooks actually refuse what they claim to =="
# A hook nobody has watched refuse something is not a hook. Both of these guard rules were broken
# for real on 2026-09-08: a pkill -9 destroyed the Steam login session, and a mute loop over every
# sink-input silenced the user's other game AND a live voice call. This check drives the guard with
# both the dangerous forms (must block, rc=2) and the legitimate lookalikes (must allow, rc=0) -
# the allow cases matter just as much, because a guard that blocks `steam -shutdown` or our own
# harness kill would make the plugin unusable.
python3 - <<'PY2'
import json, os, subprocess, sys

ROOT = "plugins/easy-red-2"
guard = os.path.join(ROOT, "scripts/guard-bash.sh")
hooks = os.path.join(ROOT, "hooks/hooks.json")
fail = []

if not os.path.exists(hooks):
    fail.append("hooks/hooks.json is missing - the operational rules are back to being comments")
else:
    cfg = json.load(open(hooks)).get("hooks", {})
    for ev in ("PreToolUse", "Stop"):
        if ev not in cfg:
            fail.append("hooks.json no longer registers a %s hook" % ev)

if not os.path.exists(guard):
    fail.append("scripts/guard-bash.sh is missing")
else:
    MUST_BLOCK = [
        "pkill -9 -x steam",
        "pkill -9 steam",
        "killall -9 steam",
        "kill -SIGKILL $(pidof steam)",
        "pactl set-sink-mute @DEFAULT_SINK@ 1",
        "for i in $(pactl list short sink-inputs | cut -f1); do pactl set-sink-input-mute $i 1; done",
    ]
    MUST_ALLOW = [
        "steam -shutdown",
        "pkill -9 -x AOE3DEHarness",
        "pactl move-sink-input 2250 er2_silence",
        "pactl list short sinks",
        "pidof steam",
    ]
    def rc(cmd):
        r = subprocess.run([guard], input=json.dumps({"tool_input": {"command": cmd}}),
                           capture_output=True, text=True, timeout=30)
        return r.returncode
    for c in MUST_BLOCK:
        got = rc(c)
        if got != 2:
            fail.append("guard ALLOWED a dangerous command (rc=%d, expected 2): %s" % (got, c))
    for c in MUST_ALLOW:
        got = rc(c)
        if got != 0:
            fail.append("guard BLOCKED a legitimate command (rc=%d, expected 0): %s" % (got, c))

if fail:
    for f in fail:
        print("FAIL  " + f)
    sys.exit(1)
print("ok    guard hooks block 6 dangerous forms and allow 5 legitimate lookalikes")
PY2
if [ $? -eq 0 ]; then ok "guard hooks enforce the operational rules"; else bad "guard hooks do not enforce what they claim"; fi

echo
echo "-------------------------------------------"
printf 'PASS %d   FAIL %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
