#!/usr/bin/env python3
"""Parse the [WATCH] observer stream and cross-tabulate GROUND TRUTH against decisions.

WHY THIS EXISTS. The project's standing handicap is its own rule: "a decision label is not proof
of behaviour." Every cover, pinned, prone and drag claim was judged by a speed threshold, and
analyse_run.py openly concedes that 16 of its labels are ungateable that way -- a man sprinting to
a wall and a man refusing to move both read as wrong against one of the two thresholds, so cover
orders are reported and never gated. That is the largest hole in the acceptance gate.

bench_watch.lua now logs what the ENGINE says is true -- isOnCover(), isMoving(), isCrawling(),
isCarryingBody(), getSuppressionValue(), getVelocity() -- all verified present on v2.0.9. It has
never had a parser, so the ground truth was collected and never read. This is that parser.

It joins each [WATCH] line to the nearest-in-time [REALISTIC] decision for the same uid, so a
claim like "PINNED means he went to ground" becomes a measured percentage instead of an argument.

Usage:  python3 watch_audit.py [Player.log] [--from-line N] [--window S]

Exit 0 always: this is an instrument, not a gate. Read the CONTRADICTIONS block.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import statistics as st
import sys

DEFAULT_LOG = os.path.expanduser("~/.config/unity3d/Corvostudio/Easy Red 2/Player.log")

# [WATCH]   #262 rifleman      enemies<90m:3  (120,340)  cover:1 move:0 crawl:1 carry:0 sup:0.72 spd:0.00
WATCH = re.compile(
    r"\[WATCH\]\s+#(?P<uid>-?\d+)\s+(?P<cls>\S+)\s*(?P<lead>\*LEAD)?\s+"
    r"enemies<(?P<r>\d+)m:(?P<near>\d+)\s+\((?P<x>-?\d+),(?P<z>-?\d+)\)"
    r"\s+cover:(?P<cover>[01?])\s+move:(?P<move>[01?])\s+crawl:(?P<crawl>[01?])"
    r"\s+carry:(?P<carry>[01?])\s+sup:(?P<sup>[\d.?]+)\s+spd:(?P<spd>[\d.?]+)"
)
SNAP = re.compile(r"\[WATCH\]\s+---\s+snapshot")
# Reuse the decision from the brain trace so the two streams can be joined.
TRACE = re.compile(
    r"\[REALISTIC\]\s+#(?P<uid>-?\d+)\s+(?:t=(?P<t>[\d.]+)\s+)?\S+\s+.*?->\s+(?P<label>[A-Za-z/-]+)"
)

# What the engine's own state SHOULD say when a branch has done its job. Only claims that a direct
# read can actually settle are listed; a label absent here is simply reported.
#   key -> (field, expected_true, note)
EXPECT = {
    "PINNED":            ("cover", True,  "suppressed men must be in cover"),
    "FIGHT-from-cover":  ("cover", True,  "the whole name of the branch"),
    "LEADER-cover":      ("cover", True,  "leader self-preservation"),
    "MEDIC-hold-cover":  ("cover", True,  "medic holds cover when threatened"),
    "SUPPORT-hold-fire": ("cover", True,  "the gun holds a firing position"),
    "ROUT-cover":        ("cover", True,  "ends in cover after falling back"),
    "ASSAULT-cover":     ("cover", True,  "cover-disciplined bound"),
    "BOUND-overwatch":   ("cover", True,  "the watching half is in cover"),
    "CREW-onfoot":       ("cover", True,  "bailed-out crew go to ground"),
    "DRAG-to-cover":     ("carry", True,  "must actually be carrying a body"),
    "DRAG-pickup":       ("carry", True,  "must actually be carrying a body"),
    "ROAD-MARCH":        ("move",  True,  "an approach march must be moving"),
    "BOUND-move":        ("move",  True,  "the moving half must be moving"),
    "DEFEND-hold":       ("move",  False, "defenders hold; they must NOT be marching"),
}


def load(path, from_line=1, window=8.0):
    """Return (rows, joined) where rows are [WATCH] samples and joined adds a decision label."""
    rows, decisions = [], collections.defaultdict(list)
    clock = 0.0
    snaps = 0
    with open(path, errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            if n < from_line:
                continue
            if SNAP.search(line):
                snaps += 1
                clock = float(snaps)          # [WATCH] has no t=; snapshot index is the clock
                continue
            m = TRACE.search(line)
            if m:
                t = m.group("t")
                if t is not None:
                    decisions[int(m.group("uid"))].append((float(t), m.group("label")))
                continue
            m = WATCH.search(line)
            if m:
                g = m.groupdict()

                def tri(v):
                    return True if v == "1" else (False if v == "0" else None)

                rows.append({
                    "snap": clock, "uid": int(g["uid"]), "cls": g["cls"],
                    "lead": bool(g["lead"]), "near": int(g["near"]),
                    "cover": tri(g["cover"]), "move": tri(g["move"]),
                    "crawl": tri(g["crawl"]), "carry": tri(g["carry"]),
                    "sup": None if g["sup"] == "?" else float(g["sup"]),
                    "spd": None if g["spd"] == "?" else float(g["spd"]),
                })

    # Join: [WATCH] carries no mission clock, so pair each uid's samples with that uid's most
    # recent decision IN ORDER. Approximate by construction -- stated, not hidden.
    joined = 0
    for r in rows:
        d = decisions.get(r["uid"])
        if d:
            r["label"] = d[min(len(d) - 1, int(r["snap"]))][1] if r["snap"] else d[0][1]
            joined += 1
    return rows, joined


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", nargs="?", default=DEFAULT_LOG)
    ap.add_argument("--from-line", type=int, default=1)
    ap.add_argument("--window", type=float, default=8.0)
    a = ap.parse_args()

    rows, joined = load(a.log, a.from_line, a.window)
    if not rows:
        print("no [WATCH] lines found. Deploy bench_watch.lua as a phase script in a TEST "
              "mission (it does NOT overwrite phase_0.lua) and set its flags.", file=sys.stderr)
        return 0

    print("[WATCH] samples %d   distinct soldiers %d   joined to a decision %d"
          % (len(rows), len({r["uid"] for r in rows}), joined))

    # ---- availability: which reads the build actually answered
    print("\nENGINE READ AVAILABILITY (a '?' column means the API returned nothing)")
    for f in ("cover", "move", "crawl", "carry", "sup", "spd"):
        got = sum(1 for r in rows if r.get(f) is not None)
        print("  %-6s answered %5d / %5d  (%5.1f%%)" % (f, got, len(rows), 100.0 * got / len(rows)))

    # ---- aggregate ground truth
    cov = [r for r in rows if r["cover"] is not None]
    mov = [r for r in rows if r["move"] is not None]
    sup = [r["sup"] for r in rows if r["sup"] is not None]
    if cov:
        print("\nGROUND TRUTH")
        print("  in cover      %5.1f%% of samples" % (100.0 * sum(1 for r in cov if r["cover"]) / len(cov)))
    if mov:
        print("  moving        %5.1f%%" % (100.0 * sum(1 for r in mov if r["move"]) / len(mov)))
    crw = [r for r in rows if r["crawl"] is not None]
    if crw:
        print("  crawling      %5.1f%%" % (100.0 * sum(1 for r in crw if r["crawl"]) / len(crw)))
    if sup:
        print("  suppression   median %.2f   p90 %.2f   share >0 %.1f%%"
              % (st.median(sup), sorted(sup)[int(0.9 * (len(sup) - 1))],
                 100.0 * sum(1 for v in sup if v > 0) / len(sup)))

    # ---- the payoff: decision vs what the engine says is true
    by = collections.defaultdict(list)
    for r in rows:
        if "label" in r:
            by[r["label"]].append(r)
    if not by:
        print("\nNo [REALISTIC] trace in this log, so decisions could not be joined. Run with")
        print("DEBUG=true in the brain to get the trace alongside the observer.")
        return 0

    print("\nDECISION vs ENGINE STATE   (n = samples for that label)")
    print("  %-22s %6s %8s %8s %8s %8s" % ("decision", "n", "inCover", "moving", "crawl", "sup"))
    contradictions = []
    for lab in sorted(by):
        rs = by[lab]
        def pct(f):
            v = [r for r in rs if r[f] is not None]
            return (100.0 * sum(1 for r in v if r[f]) / len(v)) if v else float("nan")
        c, m2 = pct("cover"), pct("move")
        cr = pct("crawl")
        sv = [r["sup"] for r in rs if r["sup"] is not None]
        print("  %-22s %6d %7s%% %7s%% %7s%% %8s"
              % (lab, len(rs),
                 "%.0f" % c if c == c else "-", "%.0f" % m2 if m2 == m2 else "-",
                 "%.0f" % cr if cr == cr else "-",
                 "%.2f" % st.median(sv) if sv else "-"))
        exp = EXPECT.get(lab)
        if exp and len(rs) >= 10:
            field, want, note = exp
            v = pct(field)
            if v == v:
                # A branch is contradicted when the engine disagrees with it most of the time.
                if want and v < 50:
                    contradictions.append((lab, field, v, want, note, len(rs)))
                elif not want and v > 50:
                    contradictions.append((lab, field, v, want, note, len(rs)))

    print("\nCONTRADICTIONS  (the engine disagreeing with the branch on a majority of samples)")
    if not contradictions:
        print("  none - every branch with >=10 samples agrees with the engine's own state")
    else:
        for lab, field, v, want, note, n in contradictions:
            if want:
                print("  %-22s %s was true on only %.0f%% of %d samples - the branch expects it"
                      % (lab, field, v, n))
            else:
                print("  %-22s %s was true on %.0f%% of %d samples - the branch expects it FALSE"
                      % (lab, field, v, n))
            print("  %-22s   %s" % ("", note))
        print("\n  A contradiction is a lead, not a verdict: the [WATCH] join has no mission clock")
        print("  and pairs samples by snapshot index, so a fast-changing decision can be mis-paired.")
        print("  Confirm with three runs before changing code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
