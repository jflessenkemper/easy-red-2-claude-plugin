#!/usr/bin/env python3
"""One-shot Steam-mode visual run of Easy Red 2: the ONLY sanctioned way to drive a DLC launch.

    python3 tools/er2_run.py --build <git-ref> --stations stations.json [--out DIR] [--dry-run]

Sequence (every step after 2 is undone in `finally`, whatever happens):
  1. ABORT if any foreign Steam game is running (virtual_pad.foreign_steam_games) - the overlay
     is shared and a launch can wreck the user's session (wiki: steam-overlay-hazard).
  2. ABORT unless Steam Launch Options already contain er2-wrap.sh %command% (never edited here).
  3. back up the deployed mission scripts (tar.gz under ~/er2-backups/).
  4. deploy the chosen build: `git worktree` of --build in ~/er2-realistic, run ITS deploy.py.
  5. touch the flag file ~/.er2harness.enabled (er2-wrap.sh switches to harness mode).
  6. launch via steam://rungameid/1324780 (server.t_launch via_steam) - no UI clicks.
  7. drive the stations; screenshots are DOWNSCALED (<= --max-width, default 960) and the
     full-res frame is deleted immediately. Full-res frames are never kept.
  8. finally: er2_stop (ownership-checked), remove flag, redeploy the SHIPPING build from the
     --shipping-ref (default master) via a worktree, verify `deploy.py --check` and DEBUG/TELEMETRY == false in deployed files.

Stations file: JSON list of steps, each one of
  {"key": "escape"} {"click": [x, y]} {"wait": 2.5} {"shot": "name"} {"mission": {"map_row": 1}}  (mission = t_play_mission args)
Evidence gate: with --evidence-features 3,16 the run is an EVIDENCE capture, and gate() refuses
before anything changes unless --eval (an eval_telemetry.py JSON from a REAL run) passes those
features (~/er2-realistic/tools/clip_gate.py). Without it, shots are written with a
manifest.json saying "exploratory: not evidence".
--dry-run performs steps 1-2 for real (read-only) and prints every other action instead.
"""
import argparse, glob, json, os, re, shutil, subprocess, sys, tarfile, time

HOME = os.path.expanduser("~")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "plugins/easy-red-2/tools")
sys.path[:0] = [TOOLS, os.path.join(TOOLS, "er2_mcp")]
MOD = os.environ.get("ER2_MOD_SRC") or os.path.join(HOME, "er2-realistic")
FLAG = os.environ.get("ER2_FLAG") or os.path.join(HOME, ".er2harness.enabled")
MISSION_ROOT = os.path.join(HOME, ".config/unity3d/Corvostudio/Easy Red 2/mission_editor")


class Abort(Exception):
    pass


def log(msg):
    print("[er2_run %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def magick():
    if shutil.which("magick"):
        return ["magick"]
    if shutil.which("host-spawn"):
        return ["host-spawn", "magick"]
    raise Abort("no ImageMagick available to downscale - refusing to keep a full-res frame")


def text_of(blocks):
    return "\n".join(b.get("text", "") for b in blocks or [] if isinstance(b, dict))


class Run:
    def __init__(self, a):
        self.a, self.dry = a, a.dry_run
        self.worktree = None
        self.out = os.path.abspath(a.out or os.path.join(ROOT, "artifacts", "run-" + time.strftime("%Y%m%d-%H%M%S")))
        self.shots = []

    def do(self, desc, fn, *args):
        if self.dry:
            log("DRY  would " + desc)
            return None
        log(desc)
        return fn(*args)

    # 1-2 ------------------------------------------------------------------------------------
    def gate(self):
        if self.a.evidence_features:
            sys.path.insert(0, os.path.join(os.path.expanduser("~/er2-realistic"), "tools"))
            import clip_gate
            ok, why = clip_gate.check(self.a.evidence_features.split(","), self.a.eval)
            log("evidence gate: " + why)
            if not ok:
                raise Abort("evidence gate: " + why)
        import virtual_pad
        foreign = virtual_pad.foreign_steam_games()
        if foreign:
            raise Abort("foreign Steam game(s) running: AppId %s - not launching. Wait or ask."
                        % ", ".join(foreign))
        log("gate: no foreign Steam game running")
        import server
        found, opts = server._steam_launch_options()
        if os.environ.get("ER2_FAKE_LAUNCH_OPTIONS") is not None:      # test seam
            found, opts = True, os.environ["ER2_FAKE_LAUNCH_OPTIONS"]
        if not found or "er2-wrap.sh" not in opts or "%command%" not in opts:
            raise Abort("Steam Launch Options for 1324780 are %r; they must be "
                        "'%s/er2-wrap.sh %%command%%'. Set them once in Steam (this tool never "
                        "edits localconfig.vdf)." % (opts if found else None, ROOT))
        log("gate: launch options use er2-wrap.sh")
        if os.path.exists(FLAG):
            raise Abort("flag %s already exists - another run in progress or a leftover; "
                        "remove it by hand after checking" % FLAG)

    # 3 ----------------------------------------------------------------------------------------
    def backup(self):
        dst = os.path.join(HOME, "er2-backups", "missions-%s.tar.gz" % time.strftime("%Y%m%d-%H%M%S"))
        def _b():
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with tarfile.open(dst, "w:gz") as t:
                for d in sorted(glob.glob(os.path.join(MISSION_ROOT, "*", "scripts"))):
                    t.add(d, arcname=os.path.relpath(d, MISSION_ROOT))
            return dst
        return self.do("back up deployed mission scripts -> %s" % dst, _b)

    # 4 ----------------------------------------------------------------------------------------
    def deploy_build(self):
        ref = self.a.build
        wt = "/tmp/er2-build-%s" % re.sub(r"[^A-Za-z0-9_.-]", "_", ref)
        def _d():
            subprocess.run(["git", "-C", MOD, "worktree", "add", "--force", "--detach", wt, ref], check=True)
            self.worktree = wt
            subprocess.run([sys.executable, os.path.join(wt, "tools/deploy.py")], check=True)
        self.do("deploy build %s (git worktree %s, its own deploy.py + check.sh gate)" % (ref, wt), _d)

    # 5-7 --------------------------------------------------------------------------------------
    def launch(self):
        def _l():
            import server
            msg = text_of(server.t_launch({"via_steam": True, "timeout_s": self.a.timeout}))
            log(msg)
            if not msg.startswith("launched via Steam"):
                raise Abort("launch did not reach a live harness")
        self.do("touch flag %s" % FLAG, lambda: open(FLAG, "w").write("1324780\n"))
        self.do("launch via steam://rungameid/1324780 and wait for the harness socket", _l)

    def shot(self, name):
        import server
        os.makedirs(self.out, exist_ok=True)
        full = os.path.join(server.TMP, "shot.png")
        reply = server.hsend(["SCREENSHOT %s" % full])[0]
        if not reply.startswith("OK"):
            raise Abort("screenshot failed: %s" % reply)
        small = os.path.join(self.out, "%02d-%s.jpg" % (len(self.shots), name))
        try:
            subprocess.run(magick() + [full, "-resize", "%dx>" % self.a.max_width, "-quality", "80", small],
                           check=True, timeout=60)
        finally:
            if os.path.exists(full):
                os.unlink(full)               # never keep the full-res frame
        self.shots.append(small)
        json.dump({"shots": [os.path.basename(x) for x in self.shots],
                   "evidence_features": self.a.evidence_features, "eval": self.a.eval,
                   "status": "evidence (eval-gated)" if self.a.evidence_features else "exploratory: not evidence"},
                  open(os.path.join(self.out, "manifest.json"), "w"), indent=1)
        log("shot %s" % small)

    def stations(self):
        steps = json.load(open(self.a.stations)) if self.a.stations else []
        for i, st in enumerate(steps):
            (k, v), = st.items()
            if k not in ("key", "click", "wait", "shot", "mission"):
                raise Abort("station %d: unknown step %r" % (i, k))
            def _s(k=k, v=v):
                import server
                if k == "wait":
                    time.sleep(float(v))
                elif k == "key":
                    log(text_of(server.t_key({"key": v})))
                elif k == "click":
                    log(text_of(server.t_click({"x": v[0], "y": v[1], "reliable": True})))
                elif k == "mission":
                    log(text_of(server.t_play_mission(dict(v))))
                elif k == "shot":
                    self.shot(v)
            self.do("station %d: %s %s" % (i, k, json.dumps(v)), _s)

    # 8 ----------------------------------------------------------------------------------------
    def teardown(self):
        errs = []
        def step(desc, fn):
            try:
                self.do(desc, fn)
            except Exception as e:            # keep going: every later step still matters
                errs.append("%s: %s" % (desc, e)); log("ERROR " + errs[-1])
        def _stop():
            import server
            log(text_of(server.t_stop({})))
        step("er2_stop (ownership-checked; only recorded pids)", _stop)
        step("remove flag %s" % FLAG, lambda: os.path.exists(FLAG) and os.unlink(FLAG))
        # The shipping build is a REF (default master), not whatever branch ~/er2-realistic has
        # checked out - on 2026-10-23 it was test/visual-check, whose deploy.py would have
        # "restored" a test build and then verified against itself.
        ship = "/tmp/er2-ship-%d" % os.getpid()
        def _ship_wt():
            subprocess.run(["git", "-C", MOD, "worktree", "add", "--force", "--detach", ship,
                            self.a.shipping_ref], check=True)
        step("check out SHIPPING ref %s into worktree %s" % (self.a.shipping_ref, ship), _ship_wt)
        step("redeploy SHIPPING build (%s)" % self.a.shipping_ref,
             lambda: subprocess.run([sys.executable, os.path.join(ship, "tools/deploy.py")], check=True))
        step("verify deploy.py --check against %s" % self.a.shipping_ref,
             lambda: subprocess.run([sys.executable, os.path.join(ship, "tools/deploy.py"), "--check"], check=True))
        step("remove worktree %s" % ship,
             lambda: subprocess.run(["git", "-C", MOD, "worktree", "remove", "--force", ship], check=True))
        step("verify DEBUG/TELEMETRY false in deployed scripts", verify_flags_false)
        if self.worktree:
            step("remove worktree %s" % self.worktree,
                 lambda: subprocess.run(["git", "-C", MOD, "worktree", "remove", "--force", self.worktree], check=True))
        return errs


def verify_flags_false(root=MISSION_ROOT):
    bad, n = [], 0
    for f in glob.glob(os.path.join(root, "*", "scripts", "mission", "*.lua")):
        src = open(f, errors="replace").read()
        for var in ("DEBUG", "TELEMETRY"):
            for m in re.finditer(r"^local %s\s*=\s*(\w+)" % var, src, re.M):
                n += 1
                if m.group(1) != "false":
                    bad.append("%s: %s = %s" % (f, var, m.group(1)))
    if bad:
        raise Abort("shipping flags not false: " + "; ".join(bad))
    if n == 0:
        raise Abort("no DEBUG/TELEMETRY declarations found under %s - nothing verified" % root)
    log("ok: %d DEBUG/TELEMETRY declarations are false" % n)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", default="HEAD", help="git ref in ~/er2-realistic to deploy for the run")
    ap.add_argument("--shipping-ref", default="master", help="git ref restored afterwards")
    ap.add_argument("--stations", help="JSON list of steps (see module doc)")
    ap.add_argument("--out", help="directory for downscaled screenshots")
    ap.add_argument("--max-width", type=int, default=960)
    ap.add_argument("--timeout", type=float, default=240)
    ap.add_argument("--evidence-features", help="comma list: this run captures evidence for these features (eval gate)")
    ap.add_argument("--eval", help="eval_telemetry.py JSON from a real run; required with --evidence-features")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.max_width > 1280:
        ap.error("--max-width above 1280 is not a downscale; full-res frames are not allowed")
    r = Run(a)
    try:
        r.gate()                      # nothing has been changed yet: abort cleanly
    except Abort as e:
        log("ABORT (nothing changed): %s" % e)
        return 2
    rc = 0
    try:
        r.backup(); r.deploy_build(); r.launch(); r.stations()
    except Exception as e:
        log("RUN FAILED: %s" % e); rc = 1
    finally:
        errs = r.teardown()
    if errs:
        log("TEARDOWN INCOMPLETE - check by hand: " + " | ".join(errs)); return 3
    log("done: %d downscaled shot(s) in %s" % (len(r.shots), r.out) if r.shots else "done")
    return rc


if __name__ == "__main__":
    sys.exit(main())
