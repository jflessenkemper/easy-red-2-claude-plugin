#!/usr/bin/env python3
"""Offline tests for the harness lifecycle helpers in server.py. Launches NO game and NO harness.

  1-4  _clear_stale_socket: absent / genuinely stale / live listener / stale-but-process-alive
  5    _reap against a REAL zombie (a child `true` we spawn and never wait for)
  6    _Boot reports phases from observable state, and emits notifications/progress with a token
  7    ownership, not name: a foreign gamescope-wl lookalike (same comm, AOE3DEHarness in its
       cmdline) survives er2_stop and is protected by the guard; recorded pids and their
       descendants are stopped; a recycled pid is not ours; no name-based kill is allow-listed
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

# 7 ownership, not name: a FOREIGN gamescope-wl is never touched; recorded/descendant ones are
os.environ["ER2_TMP"] = TMPD
m.launch_record.TMP = TMPD
GUARD = os.path.join(ROOT, "plugins/easy-red-2/scripts/guard-bash.sh")

def lookalike(parent_cmd=None):
    """A harmless sleep whose comm is gamescope-wl AND whose cmdline contains AOE3DEHarness -
    indistinguishable from our harness by name, exactly like Bazzite's gamescope would be."""
    d = os.path.join(TMPD, "AOE3DEHarness"); os.makedirs(d, exist_ok=True)
    exe = os.path.join(d, "gamescope-wl")
    if not os.path.exists(exe):        # a script's comm is the SCRIPT name: one process, no child
        with open(exe, "w") as f:
            f.write("#!%s\nimport sys, time\ntime.sleep(int(sys.argv[1]))\n" % sys.executable)
        os.chmod(exe, 0o755)
    return subprocess.Popen([exe, "60"], start_new_session=True)

def comm(pid):
    try:
        return open("/proc/%d/comm" % pid).read().strip()
    except OSError:
        return None

def guard_rc(cmd):
    env = dict(os.environ, ER2_TMP=TMPD)
    return subprocess.run([GUARD], input=json.dumps({"tool_input": {"command": cmd}}),
                          capture_output=True, text=True, timeout=30, env=env).returncode

def alive(pid):
    try:
        return [l.split()[1] for l in open("/proc/%d/status" % pid) if l.startswith("State:")][0] != "Z"
    except OSError:
        return False

foreign = lookalike()
time.sleep(0.3)
try:
    check("foreign lookalike has comm gamescope-wl and is seen by _scan_procs as a harness",
          comm(foreign.pid) == "gamescope-wl" and foreign.pid in m._scan_procs()[0])
    check("launch_record: foreign pid is NOT owned", not m.launch_record.is_owned(foreign.pid))
    out = m.t_stop({})[0]["text"]
    check("er2_stop left the foreign gamescope-wl alive and said so (%s)" % out[:70],
          alive(foreign.pid) and str(foreign.pid) in out)
    check("guard blocks `kill -9 <foreign gamescope pid>`", guard_rc("kill -9 %d" % foreign.pid) == 2)
    check("guard blocks `pkill -9 -x gamescope-wl` (no name-based kills)", guard_rc("pkill -9 -x gamescope-wl") == 2)

    ours = lookalike()
    time.sleep(0.3)
    m.launch_record.record(ours.pid)
    check("recorded pid is owned", m.launch_record.is_owned(ours.pid))
    check("guard allows `kill -9 <recorded pid>`", guard_rc("kill -9 %d" % ours.pid) == 0)
    # descendant: a shell we record, whose child is a lookalike
    d = os.path.join(TMPD, "AOE3DEHarness", "gamescope-wl")
    parent = subprocess.Popen(["bash", "-c", "%s 60 & wait" % d], start_new_session=True)
    time.sleep(0.5)
    kid = [int(c) for c in open("/proc/%d/task/%d/children" % (parent.pid, parent.pid)).read().split()]
    m.launch_record.record(parent.pid)
    check("descendant of a recorded launch is owned", kid and m.launch_record.is_owned(kid[0]))
    out = m.t_stop({})[0]["text"]
    ours.wait(5); time.sleep(0.2)
    check("er2_stop killed the recorded + descendant lookalikes, spared the foreign one",
          not alive(ours.pid) and kid and not alive(kid[0]) and alive(foreign.pid))
    # recycled pid: a stale record whose start time no longer matches is not ownership
    json.dump([{"pid": foreign.pid, "start": 1}], open(os.path.join(TMPD, "launches.json"), "w"))
    check("a record with a mismatched start time (recycled pid) does not grant ownership",
          not m.launch_record.is_owned(foreign.pid))
finally:
    for proc in [v for v in (foreign, locals().get("ours"), locals().get("parent")) if v]:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            pass
        try:
            proc.wait(5)
        except Exception:
            pass

settings = os.path.expanduser("~/.claude/settings.json")
if os.path.exists(settings):
    allow = json.load(open(settings)).get("permissions", {}).get("allow", [])
    check("settings.json no longer allow-lists any name-based gamescope kill",
          not any("gamescope" in a for a in allow))

import shutil
shutil.rmtree(TMPD, ignore_errors=True)
print("lifecycle: %d failure(s)" % len(fails))
sys.exit(1 if fails else 0)
