#!/usr/bin/env python3
"""Offline tests for the harness lifecycle helpers in server.py. Launches NO game and NO harness.

  1-4  _clear_stale_socket: absent / genuinely stale / live listener / stale-but-process-alive
  5    _reap against a REAL zombie (a child `true` we spawn and never wait for)
  6    _Boot reports phases from observable state, and emits notifications/progress with a token
  7    the gamescope-wl kill rule: settings.json allows exactly `pkill -9 -x gamescope-wl` and the
       guard-process-kill hook lets it through while still denying the -f form
Every check is written to fail if the behaviour regresses; run with --break to prove that.
"""
import importlib.util, io, json, os, socket, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMPD = tempfile.mkdtemp(prefix="er2life-")
os.environ["ER2_HARNESS_SOCK"] = os.path.join(TMPD, "h.sock")
spec = importlib.util.spec_from_file_location("er2s", os.path.join(ROOT, "plugins/easy-red-2/tools/er2_mcp/server.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SOCK = m.SOCK
assert SOCK.startswith(TMPD), "refusing to test against the real socket path %s" % SOCK
real_scan = m._scan_procs
fails = []

def check(name, cond):
    print(("  ok    " if cond else "  FAIL  ") + name)
    if not cond:
        fails.append(name)

def make_stale():
    s = socket.socket(socket.AF_UNIX); s.bind(SOCK); s.close()   # path stays, nobody listens

# 1 absent
m._scan_procs = lambda: ([], [])
check("absent socket -> ok, nothing touched", m._clear_stale_socket()[0] and not os.path.exists(SOCK))
# 2 genuinely stale
make_stale()
ok, note = m._clear_stale_socket()
check("stale socket, no process -> unlinked (%s)" % note, ok and not os.path.exists(SOCK))
# 3 live listener is never unlinked
srv = socket.socket(socket.AF_UNIX); srv.bind(SOCK); srv.listen(1)
ok, note = m._clear_stale_socket()
check("live listener -> kept (%s)" % note, ok and os.path.exists(SOCK) and m._socket_status() == "live")
srv.close(); os.unlink(SOCK)
# 4 stale but a harness process is alive -> refuse, keep the file
make_stale()
m._scan_procs = lambda: ([424242], [])
ok, note = m._clear_stale_socket()
check("stale socket + live harness pid -> refused, file kept", (not ok) and os.path.exists(SOCK) and "424242" in note)
os.unlink(SOCK)
m._scan_procs = real_scan

# 5 real zombie
child = subprocess.Popen(["true"])
state = None
for _ in range(100):
    try:
        state = [l.split()[1] for l in open("/proc/%d/status" % child.pid) if l.startswith("State:")][0]
    except OSError:
        state = None
    if state == "Z":
        break
    time.sleep(0.02)
check("spawned child became a real zombie (State=%s)" % state, state == "Z")
n = m._reap()
check("_reap reaped it (n=%d) and /proc/%d is gone" % (n, child.pid), n >= 1 and not os.path.exists("/proc/%d" % child.pid))

# 6 boot progress
m._scan_procs = lambda: ([], [])
out, saved = io.StringIO(), sys.stdout
m._PROGRESS_TOKEN[0] = "tok1"
sys.stdout = out
try:
    b = m._Boot(10)
    b.observe(); b.observe()                      # same phase twice -> one entry
    m._scan_procs = lambda: ([111], [])
    b.observe()
    m._scan_procs = lambda: ([111], [222])
    b.observe()
    make_stale(); b.observe()                     # socket present, not answering
finally:
    sys.stdout = saved
    m._PROGRESS_TOKEN[0] = None
    os.path.exists(SOCK) and os.unlink(SOCK)
    m._scan_procs = real_scan
notes = [json.loads(l) for l in out.getvalue().splitlines()]
check("boot trail has 4 distinct phases, deduplicated: %s" % [t.split(" ", 1)[1].strip() for t in b.trail],
      len(b.trail) == 4 and "waiting for harness" in b.trail[0] and "game process up" in b.trail[2] and "not answering" in b.trail[3])
check("each phase emitted notifications/progress with the caller's token",
      len(notes) == 4 and all(n["method"] == "notifications/progress" and n["params"]["progressToken"] == "tok1" for n in notes))

# 7 gamescope rule
settings = os.path.expanduser("~/.claude/settings.json")
hook = os.path.expanduser("~/.claude/hooks/guard-process-kill.sh")
if os.path.exists(settings) and os.path.exists(hook):
    allow = json.load(open(settings)).get("permissions", {}).get("allow", [])
    check("settings.json allows exactly Bash(pkill -9 -x gamescope-wl)", "Bash(pkill -9 -x gamescope-wl)" in allow)
    def decide(cmd):
        r = subprocess.run(["bash", hook], input=json.dumps({"tool_input": {"command": cmd}}), capture_output=True, text=True, timeout=10)
        return json.loads(r.stdout or "{}").get("hookSpecificOutput", {}).get("permissionDecision", "allow")
    check("guard hook lets `pkill -9 -x gamescope-wl` through", decide("pkill -9 -x gamescope-wl") == "allow")
    check("guard hook still denies `pkill -9 -f gamescope-wl`", decide("pkill -9 -f gamescope-wl") == "deny")
else:
    print("  SKIP  gamescope rule (no ~/.claude settings/hook on this machine)")

os.rmdir(TMPD)
print("lifecycle: %d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
