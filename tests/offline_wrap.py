#!/usr/bin/env python3
"""Offline tests for er2-wrap.sh and tools/er2_run.py. No game, no Steam, no harness started.

er2-wrap.sh runs with ER2_WRAP_DRY_RUN=1 (prints the argv it would exec); er2_run.py runs with
--dry-run plus the ER2_FAKE_APPIDS / ER2_FAKE_LAUNCH_OPTIONS seams, so nothing is launched,
deployed or written outside a temp dir.
"""
import os, re, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAP = os.path.join(ROOT, "er2-wrap.sh")
RUN = os.path.join(ROOT, "tools/er2_run.py")
FAIL = []


def check(cond, msg):
    print("  %s  %s" % ("ok  " if cond else "FAIL", msg))
    if not cond:
        FAIL.append(msg)


tmp = tempfile.mkdtemp()
fakeh = os.path.join(tmp, "AOE3DEHarness")
open(fakeh, "w").write("#!/bin/sh\n"); os.chmod(fakeh, 0o755)
flag = os.path.join(tmp, "flag")
base = dict(os.environ, ER2_WRAP_DRY_RUN="1", ER2_FLAG=flag, ER2_HARNESS_BIN=fakeh,
            ER2_HARNESS_SOCK=os.path.join(tmp, "s.sock"), ER2_WRAP_LOG=os.path.join(tmp, "log"),
            SteamAppId="1324780")
GAME = ["/x/reaper", "SteamLaunch", "AppId=1324780", "--", "/games/Easy Red 2/Easy Red 2.x86_64", "-a b"]


def wrap(env, args=GAME):
    r = subprocess.run([WRAP] + args, env=env, capture_output=True, text=True, timeout=20)
    return r.returncode, re.findall(r"\[([^\]]*)\]", r.stdout), r.stdout + r.stderr


rc, argv, _ = wrap(base)
check(rc == 0 and argv == GAME, "no flag -> exact passthrough, args with spaces intact")

open(flag, "w").write("1324780\n")
rc, argv, out = wrap(base)
check(argv[:1] == [fakeh] and argv[argv.index("--") + 1:] == GAME,
      "fresh flag + AppId 1324780 -> harness, then the original %command% verbatim after --")
check("--harness-socket" in argv and argv[argv.index("--harness-socket") + 1] == base["ER2_HARNESS_SOCK"],
      "harness mode passes the control socket")

e = dict(base); e.pop("SteamAppId")
rc, argv, _ = wrap(e, ["/x/other-game"])
check(argv == ["/x/other-game"], "flag present but not Easy Red 2 -> passthrough")

old = time.time() - 4000
os.utime(flag, (old, old))
rc, argv, _ = wrap(base)
check(argv == GAME, "stale flag (> ER2_FLAG_MAX_AGE_S) is ignored -> passthrough")
os.utime(flag, None)

e = dict(base, ER2_HARNESS_BIN=os.path.join(tmp, "missing"))
rc, argv, _ = wrap(e)
check(argv == GAME, "harness binary missing -> passthrough, never a broken launch")

r = subprocess.run([WRAP], env=base, capture_output=True, text=True)
check(r.returncode == 64, "no %command% -> refuses with exit 64")

# flags must not drift from the canonical launch-options writer
fx = open(os.path.join(ROOT, "tools/fix_steam_launch_options.py")).read()
flags = re.search(r'FLAGS = \((.*?)\)\n', fx, re.S).group(1)
flags = " ".join(re.findall(r'"([^"]*)"', flags)).replace("%s", "").split()
wsrc = open(WRAP).read()
check(all(f in wsrc for f in flags), "er2-wrap.sh harness flags match fix_steam_launch_options.py FLAGS")

# launch_record CLI: record our own pid into a temp record
env = dict(os.environ, ER2_TMP=tmp)
lr = os.path.join(ROOT, "plugins/easy-red-2/tools/er2_mcp/launch_record.py")
p = subprocess.Popen(["sleep", "5"])
try:
    r1 = subprocess.run([sys.executable, lr, "record", str(p.pid)], env=env).returncode
    r2 = subprocess.run([sys.executable, lr, "owned", str(p.pid)], env=env).returncode
    r3 = subprocess.run([sys.executable, lr, "owned", "1"], env=env).returncode
    check((r1, r2, r3) == (0, 0, 1), "launch_record record/owned CLI (wrapper's pid recording)")
finally:
    p.kill(); p.wait()

# orchestrator
def run(fake, opts, *extra):
    e = dict(os.environ, ER2_FAKE_APPIDS=fake, ER2_FAKE_LAUNCH_OPTIONS=opts, ER2_FLAG=flag + ".run")
    return subprocess.run([sys.executable, RUN, "--dry-run", "--out", tmp] + list(extra),
                          env=e, capture_output=True, text=True, timeout=60)

GOOD = "/var/home/jflessenkemper/er2-plugin/er2-wrap.sh %command%"
r = run("261550", GOOD)
check(r.returncode == 2 and "foreign" in r.stdout, "orchestrator ABORTS when a foreign game runs")
r = run("", "")
check(r.returncode == 2 and "er2-wrap.sh" in r.stdout, "orchestrator ABORTS when launch options lack er2-wrap.sh")
st = os.path.join(tmp, "st.json")
open(st, "w").write('[{"wait": 1}, {"key": "escape"}, {"shot": "menu"}]')
r = run("", GOOD, "--stations", st)
order = [k for k in ("back up", "deploy build", "touch flag", "steam://rungameid", "station 2: shot",
                     "er2_stop", "remove flag", "redeploy SHIPPING", "deploy.py --check", "DEBUG/TELEMETRY")
         if k in r.stdout]
check(r.returncode == 0 and len(order) == 10 and
      [r.stdout.index(k) for k in order] == sorted(r.stdout.index(k) for k in order),
      "dry run walks gate -> backup -> deploy -> flag -> launch -> stations -> full teardown, in order")
check(not os.path.exists(flag + ".run"), "dry run creates no flag file")
r = subprocess.run([sys.executable, RUN, "--dry-run", "--max-width", "1920"], capture_output=True, text=True)
check(r.returncode != 0, "full-res screenshots (--max-width 1920) are refused")

sys.path.insert(0, os.path.join(ROOT, "tools"))
import er2_run  # noqa: E402
d = os.path.join(tmp, "m", "ME_x", "scripts", "mission"); os.makedirs(d)
open(os.path.join(d, "a.lua"), "w").write("local DEBUG = false\nlocal TELEMETRY  = false\n")
try:
    er2_run.verify_flags_false(os.path.join(tmp, "m")); ok = True
except er2_run.Abort:
    ok = False
open(os.path.join(d, "b.lua"), "w").write("local TELEMETRY = true\n")
try:
    er2_run.verify_flags_false(os.path.join(tmp, "m")); bad = False
except er2_run.Abort:
    bad = True
check(ok and bad, "DEBUG/TELEMETRY verifier passes false and catches true")

print("%d failure(s)" % len(FAIL))
sys.exit(1 if FAIL else 0)
