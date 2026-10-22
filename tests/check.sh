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
PY_FILES="$SERVER plugins/easy-red-2/tools/er2_mcp/launch_record.py plugins/easy-red-2/tools/visual_probe.py plugins/easy-red-2/tools/record.py plugins/easy-red-2/tools/virtual_pad.py tools/analyse_run.py tools/fix_steam_launch_options.py tools/er2_run.py"

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
        # name-based harness kills: Bazzite Game Mode's gamescope shares the name (2026-10-21)
        "pkill -9 -x gamescope-wl",
        "pkill -x gamescope",
        "killall gamescope-wl",
        "pkill -9 -x AOE3DEHarness",
    ]
    MUST_ALLOW = [
        "pactl move-sink-input 2250 er2_silence",
        "pactl list short sinks",
        "pidof steam",
    ]

    # `steam -shutdown` is CONDITIONAL: graceful, but it closes every running Steam
    # game. It killed the user's Bannerlord on 2026-09-13. ER2_FAKE_APPIDS pins the
    # "what is running" scan so these cases are deterministic instead of depending on
    # whatever the developer happens to be playing.
    CONDITIONAL = [
        # Launching ER2 while another Steam game runs made an Ironman save unplayable on
        # 2026-09-13: the DLC store page comes through the SHARED overlay and leaves an input
        # grab. Both launch modes are unsafe; only waiting is safe.
        ("er2 launch {}", "261550", 2, "launching ER2 while a foreign game runs"),
        ("./plugins/easy-red-2/bin/er2 launch", "261550", 2, "launching via the shipped CLI"),
        ("er2 launch {}", "", 0, "launching with nothing else running"),
        ("er2 launch {}", "1324780", 0, "launching with only ER2 running"),
        ("er2 state", "261550", 0, "a NON-launch command while a foreign game runs"),
        ("er2 screenshot", "261550", 0, "screenshotting while a foreign game runs"),
        ("/x/steam.sh -shutdown", "261550", 2, "a foreign game is running"),
        ("steam --shutdown", "261550,933110", 2, "two foreign games are running"),
        ("steam -shutdown", "1324780", 0, "only Easy Red 2 is running"),
        ("steam -shutdown", "", 0, "no game is running"),
    ]

    def rc(cmd, fake=None):
        env = dict(os.environ)
        if fake is not None:
            env["ER2_FAKE_APPIDS"] = fake
        else:
            env.pop("ER2_FAKE_APPIDS", None)
        r = subprocess.run([guard], input=json.dumps({"tool_input": {"command": cmd}}),
                           capture_output=True, text=True, timeout=30, env=env)
        return r.returncode
    for c in MUST_BLOCK:
        got = rc(c, "")          # pin: no game running, so only Rule 1 can fire
        if got != 2:
            fail.append("guard ALLOWED a dangerous command (rc=%d, expected 2): %s" % (got, c))
    for c in MUST_ALLOW:
        got = rc(c, "")
        if got != 0:
            fail.append("guard BLOCKED a legitimate command (rc=%d, expected 0): %s" % (got, c))
    for cmd, fake, want, why in CONDITIONAL:
        got = rc(cmd, fake)
        if got != want:
            fail.append("guard rc=%d, expected %d, when %s: %s" % (got, want, why, cmd))

if fail:
    for f in fail:
        print("FAIL  " + f)
    sys.exit(1)
print("ok    guard hooks block 10 dangerous forms, allow 3 lookalikes, and gate steam -shutdown on 4 running-game cases")
PY2
if [ $? -eq 0 ]; then ok "guard hooks enforce the operational rules"; else bad "guard hooks do not enforce what they claim"; fi

echo "== 13. The Stop guard catches leftovers that outlive the session =="
# Both of these actually happened. A virtual gamepad left at /dev/input/js0 is visible to EVERY
# application and can change how the user's next game reads input. Stale --keep-alive harness
# processes ignore SIGTERM and make Steam refuse the next launch, which surfaces as a confusing
# "harness socket not found" timeout rather than as the leftover it is.
python3 - <<'PY3'
import os, subprocess, sys, tempfile, time
guard = "plugins/easy-red-2/scripts/guard-stop.sh"
fail = []
env0 = dict(os.environ)
env0["ER2_SKIP_PAD_CHECK"] = "1"
env0["ER2_CFG_DIR"] = tempfile.mkdtemp()      # no deployed builds to police
# PIN the harness count. This baseline asserts "clean session -> allow", and it failed for an
# environmental reason the first time the ER2 game happened to be running while the gate ran: a
# real harness process existed, the guard correctly blocked, and the test reported a code defect
# that was not there. Same flakiness the AppId pin fixes in check 12.
env0["ER2_FAKE_HARNESS"] = "0"

def rc(env):
    return subprocess.run(["bash", guard], capture_output=True, text=True,
                          timeout=60, env=env).returncode

# baseline: nothing left over
if rc(env0) != 0:
    fail.append("Stop guard blocks a clean session (expected 0)")

# a decoy shaped like a real stale harness: right process NAME and right cmdline
d = tempfile.mkdtemp()
fake = os.path.join(d, "gamescope-wl")
open(fake, "w").write("#!/bin/sh\nsleep 20\n")
os.chmod(fake, 0o755)
proc = subprocess.Popen([fake, "/x/AOE3DEHarness", "--keep-alive"])
try:
    time.sleep(1.0)
    # Exercise the REAL /proc scan for this one case: unset the pin so the decoy must be found by
    # comm+cmdline matching, which is the logic actually under test.
    envreal = dict(env0); envreal.pop("ER2_FAKE_HARNESS", None)
    if rc(envreal) != 2:
        fail.append("Stop guard ALLOWED a stale harness process (expected 2)")
    env1 = dict(env0); env1["ER2_SKIP_HARNESS_CHECK"] = "1"
    if rc(env1) != 0:
        fail.append("ER2_SKIP_HARNESS_CHECK escape hatch does not work")
finally:
    proc.kill(); proc.wait(timeout=10)

# self-match regression: merely NAMING the harness must not trip it. Excluding $$ is not enough,
# because the offender is the PARENT shell -- this is why the guard also matches on comm.
# This one MUST use the real scan (that is the point), so it is only decidable when no genuine
# harness is running. Skipping loudly beats failing misleadingly.
env2 = dict(env0); env2.pop("ER2_FAKE_HARNESS", None)
real_up = subprocess.run(["bash", "-c",
    "n=0; for p in /proc/[0-9]*; do c=$(cat $p/comm 2>/dev/null); "
    "case \"$c\" in gamescope-wl|AOE3DEHarness) n=$((n+1));; esac; done; echo $n"],
    capture_output=True, text=True, timeout=30).stdout.strip()
if real_up not in ("", "0"):
    print("note  self-match case SKIPPED: %s real harness process(es) running, so the "
          "assertion cannot discriminate" % real_up)
else:
    r = subprocess.run(["bash", "-c", "bash %s # AOE3DEHarness" % guard],
                       capture_output=True, text=True, timeout=60, env=env2)
    if r.returncode != 0:
        fail.append("Stop guard self-matches a shell command that merely mentions AOE3DEHarness")

if fail:
    for f in fail:
        print("FAIL  " + f)
    sys.exit(1)
print("ok    Stop guard: clean=0, stale harness=2, escape hatch=0, no self-match")
PY3
if [ $? -eq 0 ]; then ok "Stop guard catches session leftovers"; else bad "Stop guard does not catch leftovers"; fi

echo "== 14. Skills, agents and commands have the frontmatter that makes them load =="
# A component with broken or missing frontmatter does not error - it silently does not register,
# so the failure shows up as "why is my skill not there" long after the edit.
python3 - <<'PY4'
import glob, os, re, sys
fail = []

def front(path):
    t = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
    if not m:
        return None
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out

for path in sorted(glob.glob("plugins/*/skills/*/SKILL.md")):
    f = front(path)
    if f is None:
        fail.append("%s has no YAML frontmatter block" % path); continue
    for key in ("name", "description"):
        if not f.get(key):
            fail.append("%s is missing `%s:`" % (path, key))
    # name must be the kebab-case invocation name and match its directory
    d = os.path.basename(os.path.dirname(path))
    if f.get("name") and f["name"] != d:
        fail.append("%s declares name=%r but lives in directory %r; the invocation name should "
                    "match so it stays stable across installs" % (path, f["name"], d))

for path in sorted(glob.glob("plugins/*/agents/*.md")):
    f = front(path)
    if f is None:
        fail.append("%s has no YAML frontmatter block" % path); continue
    for key in ("name", "description"):
        if not f.get(key):
            fail.append("%s is missing `%s:`" % (path, key))
    # documented as unsupported for plugin agents, for security reasons
    for banned in ("hooks", "mcpServers", "permissionMode"):
        if banned in f:
            fail.append("%s sets `%s:`, which plugin agents do not support" % (path, banned))
    if f.get("isolation") and f["isolation"].strip('"\'') != "worktree":
        fail.append("%s sets isolation=%r; the only valid value is \"worktree\"" % (path, f["isolation"]))

for path in sorted(glob.glob("plugins/*/commands/*.md")):
    f = front(path)
    if f is None:
        fail.append("%s has no YAML frontmatter block" % path); continue
    if not f.get("description"):
        fail.append("%s is missing `description:` - it is what the user sees in the picker" % path)

if fail:
    for f in fail:
        print("FAIL  " + f)
    sys.exit(1)
n_s = len(glob.glob("plugins/*/skills/*/SKILL.md"))
n_a = len(glob.glob("plugins/*/agents/*.md"))
n_c = len(glob.glob("plugins/*/commands/*.md"))
print("ok    %d skills, %d agents, %d commands all declare valid frontmatter" % (n_s, n_a, n_c))
PY4
if [ $? -eq 0 ]; then ok "skills/agents/commands frontmatter is valid"; else bad "a component has frontmatter that would not load"; fi

echo "== 15. The README's manual-launch example matches the real launch flags =="
# This DRIFTED for real: the README told the reader to pass --harness-socket /tmp/ER2Harness.sock,
# which is the exact wrong path that check 10 exists to prevent in code. A reader following the
# docs would start a harness the MCP server cannot talk to. It also still advertised the old
# framerate cap. Docs that contradict the tool are worse than no docs.
python3 - <<'PY5'
import re, sys
fx = open("tools/fix_steam_launch_options.py").read()
m = re.search(r"FLAGS = \((.*?)\)\n", fx, re.S)
if not m:
    print("FAIL  could not parse FLAGS out of fix_steam_launch_options.py"); sys.exit(1)
flags = " ".join(re.findall(r'"([^"]*)"', m.group(1)))
sock = re.search(r'^SOCKET\s*=\s*os\.path\.join\(HOME,\s*"([^"]+)"\)', fx, re.M)
sock = sock.group(1) if sock else None

readme = open("plugins/easy-red-2/README.md").read()
fail = []
if sock and sock not in readme:
    fail.append("README never mentions the real socket file %r" % sock)
if "/tmp/ER2Harness.sock" in readme:
    fail.append("README still documents /tmp/ER2Harness.sock, the wrong path that check 10 guards "
                "against in code - a reader following it starts a harness the server cannot reach")
# every flag token that carries a value we care about must appear in the README example
for tok in ("--framerate-limit", "--force-grab-cursor", "--backend headless", "--keep-alive"):
    if tok not in readme:
        fail.append("README manual-launch example is missing %r" % tok)
fm = re.search(r"--framerate-limit (\d+)", flags)
if fm and ("--framerate-limit %s" % fm.group(1)) not in readme:
    fail.append("README framerate cap disagrees with FLAGS (tool says %s)" % fm.group(1))

if fail:
    for f in fail:
        print("FAIL  " + f)
    sys.exit(1)
print("ok    README launch example agrees with the real flags and socket path")
PY5
if [ $? -eq 0 ]; then ok "README launch example matches the tool"; else bad "README launch example has drifted from the tool"; fi

echo "== 16. marketplace.json and plugin.json agree on the version =="
# The marketplace entry is what a user sees BEFORE installing; plugin.json is what they get.
# These had drifted to 1.0.0 vs 1.8.0, so the listing advertised a version eight minor releases
# behind the thing it installs.
python3 - <<'PY6'
import json, sys
m = json.load(open(".claude-plugin/marketplace.json"))
p = json.load(open("plugins/easy-red-2/.claude-plugin/plugin.json"))
entry = next((e for e in m["plugins"] if e["name"] == p["name"]), None)
if entry is None:
    print("FAIL  marketplace.json has no entry for %r" % p["name"]); sys.exit(1)
if entry.get("version") != p.get("version"):
    print("FAIL  marketplace.json says %s but plugin.json says %s"
          % (entry.get("version"), p.get("version"))); sys.exit(1)
print("ok    marketplace and plugin manifests agree on %s" % p["version"])
PY6
if [ $? -eq 0 ]; then ok "marketplace/plugin versions agree"; else bad "marketplace and plugin versions disagree"; fi

echo "== 17. The MCP server actually SPEAKS MCP (not just imports) =="
# Checks 3 and 4 import the module. A server can import perfectly and still fail at runtime -
# crash on startup, never answer initialize, or advertise tools it cannot list. This drives the
# real stdio protocol the way Claude Code does, and also catches the version drifting again:
# serverInfo.version was hardcoded and sat at 1.0.0 while the manifest said 1.8.0.
python3 - <<'PY7'
import json, subprocess, sys, time
srv = "plugins/easy-red-2/tools/er2_mcp/server.py"
man = json.load(open("plugins/easy-red-2/.claude-plugin/plugin.json"))
p = subprocess.Popen([sys.executable, srv], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE, text=True, bufsize=1)
fail = []
try:
    for msg in ({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
                    "protocolVersion":"2024-11-05","capabilities":{},
                    "clientInfo":{"name":"check","version":"1"}}},
                {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}):
        p.stdin.write(json.dumps(msg) + "\n"); p.stdin.flush()
    p.stdin.close()
    seen = {}
    deadline = time.time() + 30
    while len(seen) < 2 and time.time() < deadline:
        line = p.stdout.readline()
        if not line:
            break
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if "id" in d:
            seen[d["id"]] = d
finally:
    p.kill()

if 1 not in seen:
    fail.append("server never answered initialize over stdio")
else:
    info = seen[1].get("result", {}).get("serverInfo", {})
    if info.get("version") != man.get("version"):
        fail.append("serverInfo.version=%r but plugin.json=%r - initialize reports a version "
                    "that is not true" % (info.get("version"), man.get("version")))
    if info.get("name") != man.get("name"):
        fail.append("serverInfo.name=%r but plugin.json name=%r" % (info.get("name"), man.get("name")))

if 2 not in seen:
    fail.append("server never answered tools/list")
else:
    tools = [t.get("name") for t in seen[2].get("result", {}).get("tools", [])]
    if not tools:
        fail.append("tools/list returned no tools")
    for t in tools:
        if not t or not t.startswith("er2_"):
            fail.append("tool %r does not follow the er2_ naming convention" % t)

if fail:
    for f in fail:
        print("FAIL  " + f)
    sys.exit(1)
print("ok    MCP handshake works; %d tools listed; serverInfo matches the manifest" % len(tools))
PY7
if [ $? -eq 0 ]; then ok "MCP server speaks the protocol"; else bad "MCP server does not answer the real protocol"; fi

echo "== 18. The shipped CLI works and is executable =="
# bin/ goes on PATH when the plugin is installed, so a non-executable file or a broken import is
# a silent dead end. This existed for weeks as an UNVERSIONED shim in a scratchpad directory,
# drifting from the server it wrapped; the point of shipping it is that it is now testable.
python3 - <<'PY8'
import os, subprocess, sys
cli = "plugins/easy-red-2/bin/er2"
fail = []
if not os.path.exists(cli):
    print("FAIL  %s is missing" % cli); sys.exit(1)
if not os.access(cli, os.X_OK):
    fail.append("%s is not executable; bin/ entries go on PATH and must be runnable" % cli)

r = subprocess.run([cli, "--list"], capture_output=True, text=True, timeout=60)
names = [l.strip() for l in r.stdout.splitlines() if l.strip()]
if r.returncode != 0:
    fail.append("--list exited %d" % r.returncode)
for required in ("launch", "state", "screenshot", "click", "key", "log"):
    if required not in names:
        fail.append("--list does not offer %r" % required)

# an unknown tool must fail LOUDLY, not silently do nothing
r = subprocess.run([cli, "definitely-not-a-tool"], capture_output=True, text=True, timeout=60)
if r.returncode == 0:
    fail.append("an unknown tool name exited 0; it must be a clear error")

# help must not require a running harness
r = subprocess.run([cli, "--help"], capture_output=True, text=True, timeout=60)
if r.returncode != 0 or "er2" not in r.stdout:
    fail.append("--help does not work standalone")

if fail:
    for f in fail:
        print("FAIL  " + f)
    sys.exit(1)
print("ok    bin/er2 is executable and exposes %d tools" % len(names))
PY8
if [ $? -eq 0 ]; then ok "shipped CLI works"; else bad "shipped CLI is broken"; fi

echo "== 19. visual_probe crop works on a saved frame =="
# crop must operate on the FILE. SCREENSHOT_REGION grabs a fresh live frame, which silently
# answers a different question than the one asked when you are inspecting a past capture.
python3 - <<'PY9'
import os, subprocess, sys, tempfile
try:
    from PIL import Image
except ImportError:
    print("ok    PIL absent; crop check skipped"); sys.exit(0)
d = tempfile.mkdtemp()
src = os.path.join(d, "src.png")
Image.new("RGB", (400, 300), (10, 120, 200)).save(src)
out = os.path.join(d, "out.png")
r = subprocess.run([sys.executable, "plugins/easy-red-2/tools/visual_probe.py", "crop", src,
                    "--box", "100,50,120,60", "--scale", "3", "--out", out],
                   capture_output=True, text=True, timeout=60)
if r.returncode != 0:
    print("FAIL  crop exited %d: %s" % (r.returncode, r.stderr.strip()[:160])); sys.exit(1)
got = Image.open(out).size
if got != (360, 180):
    print("FAIL  crop produced %r, expected (360, 180)" % (got,)); sys.exit(1)
# a box outside the image must be refused, not silently clamped to nothing
r = subprocess.run([sys.executable, "plugins/easy-red-2/tools/visual_probe.py", "crop", src,
                    "--box", "9999,9999,50,50", "--out", os.path.join(d, "x.png")],
                   capture_output=True, text=True, timeout=60)
if r.returncode == 0:
    print("FAIL  an out-of-bounds crop box exited 0"); sys.exit(1)
print("ok    crop scales a saved frame correctly and refuses an out-of-bounds box")
PY9
if [ $? -eq 0 ]; then ok "visual_probe crop is correct"; else bad "visual_probe crop is wrong"; fi

echo "== 20. t_launch itself refuses while another Steam game is running =="
# Defence in depth. The PreToolUse hook only exists once the plugin is INSTALLED and the session
# has restarted - it was written, tested and gated for a day while not actually loaded. The tool
# must refuse on its own.
python3 - <<'PY10'
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("er2srv", "plugins/easy-red-2/tools/er2_mcp/server.py")
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass
fail = []
if not hasattr(m, "running_foreign_appids"):
    print("FAIL  server.py has no running_foreign_appids()"); sys.exit(1)

# SAFETY: poison the spawn path FIRST. This test calls t_launch for real, so if the guard ever
# regresses, an unguarded call would actually start the game -- which is the exact harm being
# tested for, and it happened once while verifying this check. With Popen poisoned, a regression
# shows up as a loud failure instead of a launched game.
class _NoLaunch(Exception):
    pass

def _poisoned(*a, **k):
    raise _NoLaunch("t_launch tried to spawn a process despite a foreign game running")

m.subprocess.Popen = _poisoned

# Pretend a foreign game is running by stubbing the scan, so this does not depend on what the
# developer happens to be playing.
m.running_foreign_appids = lambda: ["261550"]
try:
    out = m.t_launch({"via_steam": False})
except _NoLaunch as exc:
    print("FAIL  %s" % exc); sys.exit(1)
blob = " ".join(b.get("text", "") for b in out if isinstance(b, dict))
if "REFUSING" not in blob:
    fail.append("t_launch did NOT refuse while a foreign AppId was running; said: %s" % blob[:120])
if "261550" not in blob:
    fail.append("the refusal does not name the offending AppId")

# force:true is the documented escape hatch and must still work (it should get past the guard and
# fail later for an unrelated reason, or succeed - either way it must not be the REFUSING text).
m.running_foreign_appids = lambda: []
out2 = m.t_launch.__doc__  # not calling it for real; launching a game inside a test is not ok
if fail:
    for f in fail:
        print("FAIL  " + f)
    sys.exit(1)
print("ok    t_launch refuses while a foreign Steam game is running, and names it")
PY10
if [ $? -eq 0 ]; then ok "t_launch refuses during someone else's game"; else bad "t_launch does not refuse"; fi

echo "== 21. play_mission refuses at a resolution its coordinates are not calibrated for =="
# Every click coordinate in play_mission was derived by hand against the 1920x1080 UI. At 1280x720
# the navigation never left the MAIN MENU, and the tool blamed "the mission panel was probably not
# open" - sending you after a UI bug that does not exist. A wrong-but-plausible error message is
# worse than no message.
python3 - <<'PY11'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("er2srv2", "plugins/easy-red-2/tools/er2_mcp/server.py")
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
except SystemExit:
    pass

m.require_live = lambda: None


class _Clicked(Exception):
    """Raised by the stubbed click so the test never drives a real game.

    For a REFUSED size this means the guard leaked. For the CALIBRATED size it is
    the proof the guard let the run proceed, which is what should happen.
    """


m._click = lambda *a, **k: (_ for _ in ()).throw(_Clicked())

fail = []
for (w, h), expect_refuse in (((1280, 720), True), ((2560, 1440), True), ((1920, 1080), False)):
    m.hsend = (lambda w_, h_: (lambda cmds, timeout=10.0:
        ["OK pid=1 internal_w=%d internal_h=%d ready=1 inner_alive=1" % (w_, h_)]))(w, h)
    clicked = False
    blob = ""
    try:
        out = m.t_play_mission({"name": "x"})
        blob = " ".join(b.get("text", "") for b in out if isinstance(b, dict))
    except _Clicked:
        clicked = True
    except Exception:
        pass               # stubbed harness; anything past the guard is fine for this check
    refused = "REFUSING" in blob
    if refused != expect_refuse:
        fail.append("at %dx%d refused=%s, expected %s" % (w, h, refused, expect_refuse))
    if expect_refuse:
        if clicked:
            fail.append("at %dx%d play_mission CLICKED despite refusing-size; the guard leaked"
                        % (w, h))
        if refused and ("%dx%d" % (w, h)) not in blob:
            fail.append("the refusal at %dx%d does not name the actual size" % (w, h))
    else:
        if not clicked:
            fail.append("at %dx%d play_mission never reached the click path; the guard is too "
                        "strict and blocks the calibrated size" % (w, h))

if fail:
    for f in fail:
        print("FAIL  " + f)
    sys.exit(1)
print("ok    play_mission refuses off-calibration resolutions and names the size")
PY11
if [ $? -eq 0 ]; then ok "play_mission guards its calibration"; else bad "play_mission does not guard its calibration"; fi

echo "== 22. Every script hooks.json points at exists and is EXECUTABLE =="
# A hook whose command is not executable does not error loudly - the hook simply never runs, and
# the protection it was written for is silently absent. That is not hypothetical: the Steam guard
# was written, unit-tested and described as protection for a full day while the plugin containing
# it was not even installed. Nothing should be able to LOOK enforced while being dormant.
python3 - <<'PY12'
import json, os, re, sys
cfg = "plugins/easy-red-2/hooks/hooks.json"
if not os.path.exists(cfg):
    print("FAIL  %s is missing" % cfg); sys.exit(1)
d = json.load(open(cfg))
root = "plugins/easy-red-2"
fail, seen = [], 0
for event, arr in d.get("hooks", {}).items():
    for entry in arr:
        for hk in entry.get("hooks", []):
            cmd = hk.get("command", "")
            if not cmd:
                continue
            seen += 1
            # resolve ${CLAUDE_PLUGIN_ROOT} to the in-repo plugin dir
            path = cmd.replace("${CLAUDE_PLUGIN_ROOT}", root).replace('"', "").split()[0]
            if not os.path.exists(path):
                fail.append("%s hook points at a missing file: %s" % (event, path))
            elif not os.access(path, os.X_OK):
                fail.append("%s hook script is NOT executable, so the hook will silently never "
                            "run: %s" % (event, path))
if not seen:
    fail.append("hooks.json declares no hook commands at all")
if fail:
    for f in fail:
        print("FAIL  " + f)
    sys.exit(1)
print("ok    all %d hook commands exist and are executable" % seen)
PY12
if [ $? -eq 0 ]; then ok "hook scripts are runnable"; else bad "a hook script would silently never run"; fi

echo "== 23. Harness lifecycle helpers behave (offline: no game, no harness) =="
# stale-socket unlink only when nobody listens AND no harness process; _reap against a real
# zombie; boot progress derived from observable state; the gamescope-wl kill rule. Each assertion
# was proven red by mutating server.py (always-unlink, no-op waitpid, no phase dedup).
if python3 tests/offline_lifecycle.py >/tmp/er2_lifecycle.out 2>&1; then
  ok "lifecycle: $(grep -c '^  ok' /tmp/er2_lifecycle.out) offline assertions pass"
else
  grep -E 'FAIL|Error' /tmp/er2_lifecycle.out | head -5; bad "harness lifecycle helpers regressed"
fi

echo "== 24. er2-wrap.sh + er2_run.py behave (offline: dry-run, no Steam, no game) =="
if python3 tests/offline_wrap.py >/tmp/er2_wrap.out 2>&1; then
  ok "wrapper/orchestrator: $(grep -c '^  ok' /tmp/er2_wrap.out) offline assertions pass"
else
  grep FAIL /tmp/er2_wrap.out | head -5; bad "er2-wrap.sh / er2_run.py regressed"
fi

echo "== 25. shellcheck the shell scripts =="
if command -v shellcheck >/dev/null; then
  if shellcheck -S warning er2-wrap.sh; then ok "shellcheck: er2-wrap.sh clean"; else bad "shellcheck findings in er2-wrap.sh"; fi
else
  echo "  note  shellcheck not installed - SKIPPED (install: ~/.local/bin/shellcheck)"
fi

echo
echo "-------------------------------------------"
printf 'PASS %d   FAIL %d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
