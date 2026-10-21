#!/usr/bin/env python3
"""Which processes did THIS plugin launch? The only basis on which anything may be killed.

Never kill a gamescope by name: Bazzite Game Mode (and Steam's own gamescope session) can run a
process with the same comm, and killing it ends the user's session. A process is ours only if

  * its pid is in the launch record (written by er2_launch the moment it spawns the harness, or
    from the harness's own STATE pid in Steam mode) AND its /proc start time still matches the
    recorded one (so a recycled pid is not ours), or
  * it is a descendant of such a recorded process (walk PPid up to init).

Record: $ER2_TMP/launches.json (default /tmp/er2_mcp), a list of {"pid", "start"}.
CLI (used by the guard hook):  launch_record.py owned PID   -> exit 0 owned, 1 not owned
"""
import json, os, sys

TMP = os.environ.get("ER2_TMP", "/tmp/er2_mcp")
PROC = os.environ.get("ER2_PROC", "/proc")


def _path():
    return os.path.join(TMP, "launches.json")


def start_time(pid):
    try:
        with open("%s/%d/stat" % (PROC, int(pid))) as f:
            return int(f.read().rsplit(")", 1)[1].split()[19])   # field 22: starttime
    except (OSError, ValueError, IndexError):
        return None


def ppid(pid):
    try:
        with open("%s/%d/status" % (PROC, int(pid))) as f:
            for line in f:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def load():
    try:
        recs = json.load(open(_path()))
    except (OSError, ValueError):
        return []
    # keep only entries whose process still exists with the same start time
    return [r for r in recs if start_time(r["pid"]) == r.get("start")]


def record(pid):
    st = start_time(pid)
    if st is None:
        return False
    recs = [r for r in load() if r["pid"] != int(pid)] + [{"pid": int(pid), "start": st}]
    os.makedirs(TMP, exist_ok=True)
    tmp = _path() + ".tmp"
    json.dump(recs, open(tmp, "w"))
    os.replace(tmp, _path())
    return True


def is_owned(pid, recs=None):
    recs = load() if recs is None else recs
    roots = {r["pid"] for r in recs}
    p, seen = int(pid), set()
    while p and p > 1 and p not in seen:
        if p in roots:
            return True
        seen.add(p)
        p = ppid(p)
    return False


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "owned":
        sys.exit(0 if is_owned(sys.argv[2]) else 1)
    print(__doc__)
    sys.exit(2)
