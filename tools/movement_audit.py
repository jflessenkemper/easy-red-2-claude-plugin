#!/usr/bin/env python3
"""Audit how every soldier actually MOVED, from Realistic-mod telemetry.

A decision label proves a branch fired. It does not prove the soldier went anywhere sensible.
This asks the questions a label cannot, and each check exists because it can distinguish a
working mod from a broken one:

  1. SPEED          A man under a move order should travel at infantry pace. A population sitting
                    near zero while ordered to move means the order is being issued and ignored
                    (the defender problem, already found once) or the path is blocked.
  2. MILLING        path/net ratio. High ratio with low net displacement = walking in circles,
                    which is what order-thrash looks like from outside.
  3. TELEPORTS      Implausible jumps between frames: either a respawn, a vehicle boarding, or a
                    genuine engine glitch. Distinguishing them matters before calling anything a bug.
  4. FROZEN         Never moved at all. Legitimate for defenders and support gunners; a red flag
                    for attackers.
  5. FORMATION      Lateral spread perpendicular to the direction of travel. This is the only
                    direct test of the staggered file: men in file spread ACROSS the axis of march,
                    a clump does not.
  6. SPACING        Nearest-neighbour distance, EXCLUDING mounted troops. Mounted men all report
                    their vehicle's position, so a truckload looks like nine men on one spot and
                    any unfiltered spacing figure is dominated by vehicle occupants.

Usage:  python3 movement_audit.py [Player.log]
"""
from __future__ import annotations

import argparse
import math
import os
import re
import statistics as st
import sys
from collections import defaultdict

RS = re.compile(r'\[TELEM\]\s+([\d.]+)\s+S\s+(.*)$')
RV = re.compile(r'\[TELEM\]\s+([\d.]+)\s+V\s+(.*)$')


def load(path):
    sol, veh = defaultdict(dict), defaultdict(list)
    for ln in open(path, "r", errors="replace"):
        m = RS.search(ln)
        if m:
            t = float(m.group(1))
            for e in m.group(2).split(";"):
                p = e.split(",")
                try:
                    if len(p) >= 8:      # uid,x,y,z,flag,squad,inVeh,dec
                        sol[t][int(p[0])] = (int(p[1]), int(p[3]), p[4], int(p[5]),
                                             int(p[6]), int(p[7]), int(p[2]))
                    elif len(p) >= 4:    # legacy uid,x,z,flag[,squad]
                        sol[t][int(p[0])] = (int(p[1]), int(p[2]), p[3],
                                             int(p[4]) if len(p) >= 5 else 0, -1, 0, 0)
                except (ValueError, IndexError):
                    pass
            continue
        m = RV.search(ln)
        if m:
            t = float(m.group(1))
            for e in m.group(2).split(";"):
                p = e.split(",")
                try:
                    if len(p) >= 5:      # uid,x,y,z,name
                        veh[t].append((int(p[1]), int(p[3]), p[4].strip()))
                    elif len(p) >= 4:
                        veh[t].append((int(p[1]), int(p[2]), ""))
                except (ValueError, IndexError):
                    pass
    return sol, veh


def side_of(flag):
    return "inv" if flag in "Ii" else ("def" if flag in "Dd" else "down")


# The DEC code -> label map, mirroring Realistic.lua's DEC.code table (the authority). Code 7
# (AT-hold-cover) was retired 2026-09-08 and the number is deliberately left as a gap so no
# parser needs renumbering. Cross-checked by er2-realistic/tests/dec_map_check.py.
DEC_NAMES = {
    1: "CREW-onfoot", 2: "MOUNTED/CREW-defer", 3: "ROUT", 4: "ROUT-cover",
    5: "AT-stalk", 6: "AT-hunt", 8: "ASSAULT", 9: "ASSAULT-cover",
    10: "PINNED", 11: "MEDIC-sortie", 12: "MEDIC-hold-cover",
    13: "DRAG-approach", 14: "DRAG-pickup", 15: "DRAG-to-cover", 16: "DRAG-abandon",
    17: "RADIO-fire-mission", 18: "LEADER-cover", 19: "SUPPORT-hold-fire",
    20: "ADVANCE-behind-armour", 21: "BOUND-move", 22: "BOUND-move-cover",
    23: "BOUND-overwatch", 24: "FIGHT-from-cover", 25: "DEFEND-hold",
    26: "CONSOLIDATE", 27: "RALLY-on-MG", 28: "ROAD-MARCH", 29: "ADVANCE-baseAI",
    30: "RETURN-to-transport", 31: "REBOARD-transport", 32: "FORM-followLeader",
}



def formation(sol, veh, dec=None):
    """Per-squad anisotropy: sigma ACROSS the line of travel vs sigma ALONG it, and the ratio.

    `dec` filters to a single decision code, which is the whole point of factoring this out.
    The pooled (dec=None) version cannot test a squad-level feature: RALLY-on-MG is 5.48% of
    soldier samples (1142/20842 in base2), so a formation change there is diluted roughly 18:1 in
    the pooled figure -- far below the metric's own 0.20-0.23 run-to-run spread. The one analysis
    that ever produced real Kette evidence was this, computed by hand and never committed.

    Returns (across_m, along_m, ratio, squad_frames, samples). `squad_frames` is the number of
    (frame, squad) groups that cleared the >=3-mover filter and `samples` the total men in them --
    both reported because a ratio over 4 squad-frames is not the same claim as one over 89, and
    the population itself is wildly unstable: two identical-configuration runs produced 0 and 89.

    Anisotropy, not interval, deliberately. Every doctrinal interval is sub-sigma against the
    engine's ~13 m pathing scatter (Schuetzenkette 4-5 m is 0.31-0.38 sigma), so a file and a line
    are indistinguishable by construction unless you measure axis and extent.
    """
    ts = sorted(sol)
    lat, lon, ratio = [], [], []
    frames = samples = 0
    for i in range(1, len(ts)):
        t0, t1 = ts[i - 1], ts[i]
        vs = veh.get(t1, [])
        squads = {}
        for uid, e in sol[t1].items():
            x, z, f, sq = e[0], e[1], e[2], e[3]
            if sq == 0 or side_of(f) != "inv":
                continue
            if dec is not None and e[5] != dec:
                continue
            prev = sol[t0].get(uid)
            if not prev:
                continue
            d = math.dist((prev[0], prev[1]), (x, z))
            if d < 1.0 or d > 40:
                continue
            # Mounted men all report the VEHICLE's position, so a truckload reads as nine men on
            # one spot. This faked a 1.0 m median spacing that was really 32 m.
            if e[4] == 1 or (e[4] == -1 and vs and min(math.dist((x, z), v[:2]) for v in vs) <= 4):
                continue
            squads.setdefault(sq, []).append(((x, z), ((x - prev[0]) / d, (z - prev[1]) / d)))
        for sq, pts in squads.items():
            if len(pts) < 3:
                continue
            hx = st.mean(p[1][0] for p in pts); hz = st.mean(p[1][1] for p in pts)
            n = math.hypot(hx, hz)
            if n < 0.3:          # no coherent direction of travel: no axis to measure against
                continue
            hx, hz = hx / n, hz / n
            px, pz = -hz, hx
            a = st.pstdev([p[0][0] * px + p[0][1] * pz for p in pts])
            b = st.pstdev([p[0][0] * hx + p[0][1] * hz for p in pts])
            lat.append(a); lon.append(b)
            frames += 1
            samples += len(pts)
            if a > 0.01:
                ratio.append(b / a)
    return (st.median(lat) if lat else float("nan"),
            st.median(lon) if lon else float("nan"),
            st.median(ratio) if ratio else float("nan"),
            frames, samples)


SENSE_RADIUS = 90            # must match Realistic.lua: the brain's own sensing horizon


def approach(sol, dec, side="inv", radius=SENSE_RADIUS):
    """Did men on this decision move TOWARD or AWAY FROM the enemy THEY CAN SEE? Signed m/frame.

    Scalar displacement cannot answer this, and several pass criteria are exactly this question:
    ROUT must move AWAY, ASSAULT must CLOSE, a bailed-out crew must break contact. A man can cover
    40 m on either and the existing `net` figure reads identically.

    Returns (median_delta, n). NEGATIVE = closing, POSITIVE = withdrawing.

    The reference is the centroid of enemies within `radius` OF THAT MAN, recomputed per man per
    frame, deliberately matching the brain's own SENSE_RADIUS -- because the brain decides against
    what it senses, so that is the only reference the decision can be judged against.

    A GLOBAL enemy centroid, which is what this first computed, is worse than useless: it made
    both ROUT (-2.21) and ASSAULT (+1.97) come out INVERTED on the banked control. ASSAULT fires
    at <=35 m and ROUT at 40 m; both are local actions, and on a battalion-scale map the army's
    average position is nowhere near the fight a given man is in. Two whole classes of result
    reading wrong at once was the tell that the instrument, not the mod, was broken.
    """
    ts = sorted(sol)
    other = "def" if side == "inv" else "inv"
    deltas, own = [], []
    for i in range(1, len(ts)):
        t0, t1 = ts[i - 1], ts[i]
        gap = t1 - t0
        if gap <= 0 or gap > 20:
            continue
        foe = [(e[0], e[1]) for e in sol[t0].values() if side_of(e[2]) == other]
        if not foe:
            continue
        for uid, e in sol[t1].items():
            if e[5] != dec or side_of(e[2]) != side or e[4] == 1:
                continue
            prev = sol[t0].get(uid)
            if not prev:
                continue
            if math.dist((prev[0], prev[1]), (e[0], e[1])) / gap > 25:
                continue                     # teleport / respawn
            local = [p for p in foe if math.dist((prev[0], prev[1]), p) <= radius]
            if len(local) < 2:               # no sensed enemy: nothing to close on or flee from
                continue
            cx = st.mean(p[0] for p in local); cz = st.mean(p[1] for p in local)
            was = math.dist((prev[0], prev[1]), (cx, cz))
            now = math.dist((e[0], e[1]), (cx, cz))
            deltas.append(now - was)

            # OWN-MOTION measure, and it answers a DIFFERENT question from the one above.
            #
            # `now - was` is the change in DISTANCE to a centroid that is itself moving. If the
            # enemy advances faster than the man retreats, it reports "closing" even though the
            # man moved away - so it cannot distinguish "he ran the wrong way" from "he ran the
            # right way and they chased him". That ambiguity is exactly what made ROUT read
            # -0.91 m/frame and look like a defect while fallbackFrom() is geometrically correct
            # (pos - ec is the vector FROM the enemy; it moves 40 m further along it).
            #
            # This projects the SOLDIER'S OWN displacement onto the unit vector pointing away
            # from the enemy centroid AT THE START FRAME. The axis is fixed, so the enemy's
            # movement cannot contaminate it. POSITIVE = he moved away under his own steam.
            ax, az = prev[0] - cx, prev[1] - cz
            amag = math.hypot(ax, az)
            if amag > 0.001:
                ax, az = ax / amag, az / amag
                own.append((e[0] - prev[0]) * ax + (e[1] - prev[1]) * az)
    return ((st.median(deltas) if deltas else float("nan")), len(deltas),
            (st.median(own) if own else float("nan")))


def near_vehicle(sol, veh, dec, name_sub=None, radius=25):
    """Join soldiers on a decision to the nearest NAMED vehicle. Returns (median_m, n, names).

    ADVANCE-behind-armour claims men sit ~ARMOUR_HUG 6 m behind a hull; nothing could check it,
    because no tool joined a soldier to a vehicle. `name_sub` filters to a vehicle whose name
    contains that substring, which is how the T6 negative control works: with an Opel Blitz
    instead of a halftrack the branch must not qualify at all.

    Caveat worth stating: ARMOUR_HUG 6 m and ARMOUR_SPREAD 2.5 m are both sub-sigma against the
    engine's ~13 m pathing scatter, so treat a single figure here as weak evidence.
    """
    ts = sorted(sol)
    ds, seen = [], defaultdict(int)
    for t in ts:
        vs = veh.get(t, [])
        if name_sub:
            vs = [v for v in vs if name_sub.lower() in (v[2] or "").lower()]
        if not vs:
            continue
        for uid, e in sol[t].items():
            if e[5] != dec or e[4] == 1:
                continue
            best, bn = 1e9, None
            for v in vs:
                d = math.dist((e[0], e[1]), v[:2])
                if d < best:
                    best, bn = d, v[2]
            if best <= radius:
                ds.append(best)
                seen[bn or "(unnamed)"] += 1
    return (st.median(ds) if ds else float("nan")), len(ds), dict(seen)


def sequences(sol):
    """Ordered transitions, alternation ratios and election uniqueness.

    Three pass criteria that nothing could check:
      * DRAG-approach -> DRAG-pickup -> DRAG-to-cover must occur IN THAT ORDER for one man
      * BOUND-move : BOUND-overwatch must sit near 1:1 (the squad alternates halves every 8 s)
      * exactly ONE man may be elected to a casualty, or two men fight over the same body

    `dec` is latched change-only in telemetry, so a per-soldier decision sequence is a sequence of
    CHANGES, which is exactly what a transition check wants.
    """
    ts = sorted(sol)
    seq = defaultdict(list)
    for t in ts:
        for uid, e in sol[t].items():
            d = e[5]
            if d == 0:
                continue
            if not seq[uid] or seq[uid][-1][1] != d:
                seq[uid].append((t, d))

    out = {}
    # DRAG: 13 approach -> 14 pickup. A pickup with NO preceding approach is not automatically
    # wrong - CARRY_ADJACENT is 3 m, so a man already standing on the casualty short-circuits
    # straight to pickup. Reported as "direct" rather than "bad" for that reason.
    ordered = direct = 0
    for uid, s in seq.items():
        codes = [d for _, d in s]
        for i in range(len(codes) - 1):
            if codes[i] == 13 and 14 in codes[i + 1:i + 3]:
                ordered += 1
            elif codes[i] == 14 and (i == 0 or codes[i - 1] != 13):
                direct += 1
    out["drag_ordered_vs_direct_pickup"] = (ordered, direct)

    # BOUND alternation: count men-frames, not transitions, so a long bound is not one tick
    mv = sum(1 for t in ts for e in sol[t].values() if e[5] in (21, 22))
    ow = sum(1 for t in ts for e in sol[t].values() if e[5] == 23)
    out["bound_move_vs_overwatch"] = (mv, ow, (mv / ow) if ow else float("nan"))

    # Concurrent draggers MAP-WIDE. This is deliberately NOT the "exactly one man per casualty"
    # claim: telemetry carries no casualty identity, so twelve draggers may be twelve men each on
    # a different body, which is correct behaviour. What it CAN catch is a runaway - a figure of
    # the same order as the whole battalion means the election is not electing.
    worst = 0
    for t in ts:
        worst = max(worst, sum(1 for e in sol[t].values() if e[5] in (13, 14, 15)))
    out["max_concurrent_draggers_mapwide"] = worst
    # Cluster them by proximity: draggers within 30 m (DRAG_RADIUS) of each other in one frame
    # are plausibly contesting ONE casualty, which IS the uniqueness question.
    clustered = 0
    for t in ts:
        pts = [(e[0], e[1]) for e in sol[t].values() if e[5] in (13, 14, 15)]
        for i, p in enumerate(pts):
            n = sum(1 for j, q in enumerate(pts) if j != i and math.dist(p, q) <= 30)
            clustered = max(clustered, n + 1)
    out["max_draggers_within_30m"] = clustered
    return out


def headline(sol, veh):
    """The handful of numbers worth comparing BETWEEN runs, as a dict.

    Deliberately small. The point is not more numbers, it is knowing each one's run-to-run spread
    before anyone claims a change moved it: two identical-configuration battles produced
    along/across ratios of 1.19 and 1.39, so a single run showing 1.45 proves nothing.
    """
    ts = sorted(sol)
    out = {}
    a, b, r, _, _ = formation(sol, veh)
    out["across_m"], out["along_m"], out["ratio"] = a, b, r

    per = defaultdict(list)
    for i in range(1, len(ts)):
        gap = ts[i] - ts[i - 1]
        if gap <= 0 or gap > 20:
            continue
        for uid, e in sol[ts[i]].items():
            dec = e[5]
            if dec == 0 or e[4] == 1:
                continue
            prev = sol[ts[i - 1]].get(uid)
            if not prev:
                continue
            d = math.dist((prev[0], prev[1]), (e[0], e[1]))
            if d / gap > 25:
                continue
            per[dec].append(d / gap)
    out["roadmarch_mps"] = st.median(per[28]) if len(per.get(28, [])) >= 15 else float("nan")
    out["advarmour_mps"] = st.median(per[20]) if len(per.get(20, [])) >= 15 else float("nan")

    frozen = tot = 0
    tr = defaultdict(list)
    for t in ts:
        for uid, e in sol[t].items():
            tr[uid].append((t, e[0], e[1], e[2]))
    for uid, k in tr.items():
        if len(k) < 6 or side_of(k[-1][3]) != "inv":
            continue
        tot += 1
        if sum(math.dist(k[j][1:3], k[j + 1][1:3]) for j in range(len(k) - 1)) < 5:
            frozen += 1
    out["inv_frozen_pct"] = (100.0 * frozen / tot) if tot else float("nan")
    return out


# Known run-to-run spread of the formation ratio, from two pairs of identical-configuration
# battles: 1.19 vs 1.39 (0.20) and a separately recorded 0.23. Use the WIDER figure -- an effect
# has to clear the worst observed noise, not the kindest.
RATIO_SPREAD = 0.23
ROADMARCH_SPREAD = 0.73
MIN_RUNS = 3


def compare(paths, claim=None, strict=True):
    """Report each headline metric across several runs, WITH its spread, and REFUSE weak claims.

    This exists because of a real mistake: a formation change was read as an improvement from one
    battle, when the metric's own run-to-run spread was larger than the effect. It used to print
    an advisory sentence and exit 0, which is exactly the failure mode it was written to prevent --
    nothing mechanically stopped the claim. Now it exits non-zero.

    Two refusals:
      * fewer than MIN_RUNS runs of a configuration -- two points cannot establish a band
      * a claimed delta (--claim METRIC=DELTA) no larger than the measured spread
    """
    rows = []
    for pth in paths:
        sol, veh = load(pth)
        if not sol:
            print("  (no telemetry in %s - skipped)" % pth, file=sys.stderr)
            continue
        rows.append((os.path.basename(pth), headline(sol, veh)))
    if len(rows) < 2:
        print("need at least two logs WITH telemetry to compare", file=sys.stderr)
        return 1
    keys = ["ratio", "across_m", "along_m", "roadmarch_mps", "advarmour_mps", "inv_frozen_pct"]
    print("%-16s" % "metric" + "".join("%12s" % r[0][:11] for r in rows)
          + "%8s%10s%10s" % ("n", "spread", "verdict"))
    spreads = {}
    for k in keys:
        vals = [r[1].get(k, float("nan")) for r in rows]
        good = [v for v in vals if v == v]
        line = "%-16s" % k + "".join(("%12.2f" % v if v == v else "%12s" % "-") for v in vals)
        line += "%8d" % len(good)
        if len(good) >= 2:
            sp = max(good) - min(good)
            spreads[k] = sp
            line += "%10.2f" % sp
            line += "%10s" % ("noisy" if sp > 0.15 * max(1e-9, abs(st.mean(good))) else "stable")
        else:
            line += "%10s%10s" % ("-", "no band")
        print(line)

    rc = 0
    print("\nAny difference smaller than the spread column is NOT evidence of a change.")
    if len(rows) < MIN_RUNS:
        print("REFUSED: %d run(s) of this configuration; %d are needed to establish a band. "
              "Two points are a line, not a distribution." % (len(rows), MIN_RUNS))
        if strict:
            rc = 2

    if claim:
        try:
            metric, delta = claim.split("=", 1)
            delta = abs(float(delta))
        except ValueError:
            print("bad --claim (want METRIC=DELTA, e.g. ratio=0.31)", file=sys.stderr)
            return 1
        # Prefer this run's own measured spread; fall back to the recorded historical figure, so a
        # claim can still be judged against something when only one configuration was supplied.
        band = spreads.get(metric)
        src = "measured here"
        if band is None or len(rows) < MIN_RUNS:
            band = {"ratio": RATIO_SPREAD, "roadmarch_mps": ROADMARCH_SPREAD}.get(metric)
            src = "recorded historical spread"
        if band is None:
            print("REFUSED: no spread available for '%s' - run %d configurations of it first"
                  % (metric, MIN_RUNS))
            return 2 if strict else 0
        if delta > band:
            print("SUPPORTED: claimed %s delta %.3f EXCEEDS the %s %.3f" % (metric, delta, src, band))
        else:
            print("REFUSED: claimed %s delta %.3f is INSIDE the %s %.3f - not evidence"
                  % (metric, delta, src, band))
            if strict:
                rc = 2
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", nargs="*", default=[os.path.expanduser(
        "~/.config/unity3d/Corvostudio/Easy Red 2/Player.log")])
    ap.add_argument("--compare", action="store_true",
                    help="compare headline metrics across several logs, with their spread")
    ap.add_argument("--claim", metavar="METRIC=DELTA",
                    help="assert a change of DELTA in METRIC; exits 2 if it is inside the spread")
    ap.add_argument("--no-strict", action="store_true",
                    help="report refusals but still exit 0")
    a = ap.parse_args()
    logs = a.log if isinstance(a.log, list) else [a.log]
    if a.compare or len(logs) > 1 or a.claim:
        return compare(logs, claim=a.claim, strict=not a.no_strict)
    a.log = logs[0]

    sol, veh = load(a.log)
    if not sol:
        print("no [TELEM] soldier frames found", file=sys.stderr)
        return 1
    ts = sorted(sol)
    dt = st.median([ts[i + 1] - ts[i] for i in range(len(ts) - 1)]) if len(ts) > 1 else 2.0
    print(f"frames {len(ts)}   span {ts[-1]-ts[0]:.0f}s   cadence {dt:.1f}s")

    # per-soldier track
    tr = defaultdict(list)
    for t in ts:
        for uid, e in sol[t].items():
            tr[uid].append((t, e[0], e[1], e[2]))

    # ---- 1/2/3/4 : speed, milling, teleports, frozen
    print("\n--- movement per soldier (tracks with >= 6 frames)")
    rows = {"inv": [], "def": []}
    teleports = []
    for uid, k in tr.items():
        if len(k) < 6:
            continue
        segs, path = [], 0.0
        for i in range(len(k) - 1):
            d = math.dist(k[i][1:3], k[i + 1][1:3])
            gap = max(1e-6, k[i + 1][0] - k[i][0])
            v = d / gap
            path += d
            if v > 25:                       # 25 m/s ~ 90 km/h: not a man on foot
                teleports.append((uid, k[i][0], round(d), round(v, 1)))
            else:
                segs.append(v)
        net = math.dist(k[0][1:3], k[-1][1:3])
        s = side_of(k[-1][3])
        if s in rows:
            movers = [v for v in segs if v > 0.15]
            rows[s].append({
                "uid": uid, "path": path, "net": net,
                "vmed": st.median(movers) if movers else 0.0,
                "vmax": max(segs) if segs else 0.0,
                "moving_frac": len(movers) / max(1, len(segs)),
                "mill": path / net if net > 1 else (999 if path > 30 else 0),
            })
    for s in ("inv", "def"):
        R = rows[s]
        if not R:
            continue
        f = lambda k: sorted(r[k] for r in R)
        n = len(R)
        frozen = [r for r in R if r["path"] < 5]
        mill = [r for r in R if r["mill"] > 6 and r["net"] < 40 and r["path"] > 60]
        print(f"\n {s}: n={n}")
        print(f"   path   median {f('path')[n//2]:7.0f} m   p90 {f('path')[int(n*.9)]:7.0f} m")
        print(f"   net    median {f('net')[n//2]:7.0f} m   p90 {f('net')[int(n*.9)]:7.0f} m")
        print(f"   speed  median {f('vmed')[n//2]:7.2f} m/s (while moving)   max seen {max(r['vmax'] for r in R):.1f} m/s")
        print(f"   moving {100*st.median([r['moving_frac'] for r in R]):5.0f}% of frames (median)")
        print(f"   frozen (<5 m total)      {len(frozen):4d}  ({100*len(frozen)/n:.0f}%)")
        print(f"   milling (path/net>6)     {len(mill):4d}  ({100*len(mill)/n:.0f}%)")
    print(f"\n teleports/jumps >25 m/s: {len(teleports)}"
          + (f"  e.g. {teleports[:3]}" if teleports else "  (none)"))

    # ---- 5 : formation - lateral spread across the axis of march
    print("\n--- formation: spread ACROSS the direction of travel (dismounted movers only)")
    lat_all = []
    for t_i in range(1, len(ts)):
        t0, t1 = ts[t_i - 1], ts[t_i]
        vs = veh.get(t1, [])
        pts = []
        for uid, e in sol[t1].items():
            x, z, f = e[0], e[1], e[2]
            if side_of(f) != "inv":
                continue
            prev = sol[t0].get(uid)
            if not prev:
                continue
            d = math.dist((prev[0], prev[1]), (x, z))
            if d < 1.0 or d > 40:
                continue                     # stationary, or a boarding jump
            if e[4] == 1 or (e[4] == -1 and vs and min(math.dist((x, z), v[:2]) for v in vs) <= 4):
                continue                     # mounted: reports the vehicle position
            pts.append(((x, z), ((x - prev[0]) / d, (z - prev[1]) / d)))
        if len(pts) < 6:
            continue
        # mean heading, then spread of positions along the perpendicular
        hx = st.mean(p[1][0] for p in pts)
        hz = st.mean(p[1][1] for p in pts)
        n = math.hypot(hx, hz)
        if n < 0.3:                          # no coherent direction: skip this frame
            continue
        hx, hz = hx / n, hz / n
        px, pz = -hz, hx
        proj = [p[0][0] * px + p[0][1] * pz for p in pts]
        lat_all.append(st.pstdev(proj) if len(proj) > 1 else 0)
    if lat_all:
        print(f"   frames measured {len(lat_all)}")
        print(f"   lateral spread (std dev across axis): median {st.median(lat_all):.1f} m"
              f"   p10 {sorted(lat_all)[int(len(lat_all)*.1)]:.1f} m"
              f"   p90 {sorted(lat_all)[int(len(lat_all)*.9)]:.1f} m")
        print("   a single-file clump would sit near 0; a dispersed advance spreads across the axis")
    else:
        print("   not enough coherent dismounted movement to measure")

    # ---- 4b : INTENT vs OUTCOME - the check the decision codes make possible
    # A move order that produces no movement is the single most important failure this mod can
    # have, and it has happened for real: defenders were issued moveTo orders they silently
    # ignored, measured at 0.34 m/s across 21 soldiers. Joining each man's own decision to his
    # own displacement is the only way to catch that class of bug directly.
    MOVE = {21:"BOUND-move", 22:"BOUND-move-cover", 20:"ADVANCE-behind-armour", 28:"ROAD-MARCH",
            27:"RALLY-on-MG", 13:"DRAG-approach", 5:"AT-stalk", 8:"ASSAULT", 30:"RETURN-to-transport"}
    HOLD = {23:"BOUND-overwatch", 10:"PINNED", 24:"FIGHT-from-cover", 25:"DEFEND-hold",
            19:"SUPPORT-hold-fire", 18:"LEADER-cover", 12:"MEDIC-hold-cover", 26:"CONSOLIDATE",
            1:"CREW-onfoot", 4:"ROUT-cover"}
    NAMES = dict(MOVE); NAMES.update(HOLD)
    per = defaultdict(list)
    for i in range(1, len(ts)):
        t0, t1 = ts[i-1], ts[i]
        gap = t1 - t0
        if gap <= 0 or gap > 20:
            continue
        for uid, e in sol[t1].items():
            dec = e[5] if len(e) > 5 else 0
            if dec == 0 or e[4] == 1:            # unknown, or mounted
                continue
            prev = sol[t0].get(uid)
            if not prev:
                continue
            d = math.dist((prev[0], prev[1]), (e[0], e[1]))
            if d / gap > 25:                     # aircraft
                continue
            per[dec].append(d / gap)
    if per:
        print("\n--- INTENT vs OUTCOME: speed while on each decision (dismounted, m/s)")
        print(f"    {'decision':24s} {'n':>6s} {'median':>7s} {'p90':>6s}  verdict")
        for dec in sorted(per, key=lambda k: -len(per[k])):
            v = sorted(per[dec]); n = len(v)
            if n < 15:
                continue
            med, p90 = v[n//2], v[int(n*.9)]
            name = NAMES.get(dec, f"code {dec}")
            if dec in MOVE:
                verdict = "MOVES" if med > 0.5 else ("weak" if med > 0.2 else "*** ORDERED BUT STATIC ***")
            elif dec in HOLD:
                verdict = "holds" if med < 1.2 else "moving while holding?"
            else:
                verdict = ""
            print(f"    {name:24s} {n:6d} {med:7.2f} {p90:6.2f}  {verdict}")
    else:
        print("\n--- INTENT vs OUTCOME: no decision codes in this log (older telemetry format)")

    # ---- 5b : formation PER SQUAD - the only direct test of a formation change
    # A section in file spreads ALONG its axis of march and stays narrow ACROSS it. A blob spreads
    # equally both ways. Measuring the whole force instead just reports army frontage, which swamps
    # the few metres that separate two files of one section.
    #
    # Both the pooled figure AND a per-decision breakdown are printed, because the pooled one
    # CANNOT test a squad-level feature: RALLY-on-MG is ~5% of soldier samples, so a change there
    # is diluted ~18:1 - far under the metric's own 0.20-0.23 run-to-run spread. Read the row for
    # the branch you actually changed, and read its n before believing its ratio.
    print("\n--- formation PER SQUAD (dismounted, moving, >=3 men in the squad)")
    a, b, r, frames, samples = formation(sol, veh)
    if frames:
        print(f"   squad-frames measured {frames}  (men sampled {samples})")
        print(f"   ACROSS the axis (should be small): median {a:5.1f} m")
        print(f"   ALONG  the axis (should be larger): median {b:5.1f} m")
        if r == r:
            print(f"   along/across ratio: median {r:.2f}"
                  f"   ( >1 = strung out in file, ~1 = a blob )")
    else:
        print("   no squad had 3+ dismounted movers in a frame - cannot measure")

    print("\n--- formation BY DECISION (isolates the branch; n matters more than the ratio)")
    hdr = False
    for dec in sorted(DEC_NAMES):
        da, db, dr, df, dsm = formation(sol, veh, dec)
        if df == 0:
            continue
        if not hdr:
            print("   %-24s %7s %7s %7s %8s %8s"
                  % ("decision", "across", "along", "ratio", "frames", "men"))
            hdr = True
        print("   %-24s %7.1f %7.1f %7s %8d %8d"
              % (DEC_NAMES[dec], da, db, ("%.2f" % dr) if dr == dr else "-", df, dsm))
    if not hdr:
        print("   no decision code had a measurable squad-frame")

    # ---- 5c : direction relative to the LOCAL sensed enemy, and order sequencing
    # A scalar displacement cannot tell a rout from a charge. These can.
    print("\n--- direction vs the enemy the man can SEE (- closes, + withdraws)")
    print("   %-24s %8s %9s %8s   %s"
          % ("decision", "vs foe", "own move", "n", "expected"))
    print("   (vs foe = change in distance to a MOVING enemy centroid; own move = the soldier's")
    print("    OWN displacement along the fixed away-from-enemy axis. POSITIVE = away.)")
    EXPECT = {3: "AWAY", 4: "AWAY", 1: "AWAY (break contact)",
              8: "CLOSE", 9: "CLOSE", 28: "CLOSE", 20: "CLOSE", 21: "CLOSE", 22: "CLOSE"}
    for dec in sorted(DEC_NAMES):
        d, n, ownd = approach(sol, dec)
        if n < 5:                     # under five samples is not a direction, it is noise
            continue
        want = EXPECT.get(dec, "")
        flag = ""
        # 0.5 m/frame deadband: a median of exactly 0.00 means the men did not move at all, which
        # is a DIFFERENT fault from moving the wrong way, and mislabelling it "moves away" would be
        # the same sloppiness this tool exists to prevent.
        # Judge on OWN motion where available: it is the unambiguous signal.
        j = ownd if ownd == ownd else d
        if want and abs(j) < 0.5:
            flag = "  <-- STATIC (ordered to move, did not)" if want == "CLOSE" else "  <-- STATIC"
        elif want.startswith("AWAY") and j <= -0.5:
            flag = "  <-- MOVES TOWARD THE ENEMY"
        elif want == "CLOSE" and j >= 0.5:
            flag = "  <-- MOVES AWAY FROM THE ENEMY"
        print("   %-24s %+8.2f %+9.2f %8d   %s%s"
              % (DEC_NAMES[dec], d, ownd, n, want, flag))

    print("\n--- soldier-to-vehicle join, ADVANCE-behind-armour (ARMOUR_HUG is 6 m)")
    m, n, names = near_vehicle(sol, veh, 20)
    if n:
        top = sorted(names.items(), key=lambda kv: -kv[1])[:4]
        print("   median distance to nearest vehicle %.1f m over %d man-frames" % (m, n))
        print("   nearest vehicle was: " + ", ".join("%s x%d" % (k, v) for k, v in top))
        print("   NOTE ARMOUR_HUG 6 m and ARMOUR_SPREAD 2.5 m are both sub-sigma against ~13 m")
        print("        pathing scatter, so treat one figure as weak evidence.")
    else:
        print("   no ADVANCE-behind-armour man-frames with a vehicle in range")

    print("\n--- order sequencing, alternation and election")
    sq = sequences(sol)
    o, dr = sq["drag_ordered_vs_direct_pickup"]
    print("   DRAG approach->pickup ordered %d, straight-to-pickup %d "
          "(the latter is legitimate inside CARRY_ADJACENT 3 m)" % (o, dr))
    mv, ow, rat = sq["bound_move_vs_overwatch"]
    verdict = "~1:1 as designed" if 0.6 <= rat <= 1.7 else "NOT the designed 1:1 alternation"
    print("   BOUND move %d : overwatch %d  ratio %.2f  %s"
          % (mv, ow, rat, verdict) if rat == rat else
          "   BOUND move %d : overwatch %d  (no overwatch frames)" % (mv, ow))
    print("   max concurrent draggers map-wide %d, within 30 m of each other %d"
          % (sq["max_concurrent_draggers_mapwide"], sq["max_draggers_within_30m"]))
    print("   (map-wide is NOT the uniqueness test - telemetry has no casualty identity, so")
    print("    twelve draggers may be twelve separate bodies. The 30 m figure is the real one.)")

    # ---- 6 : spacing, mounted excluded
    print("\n--- spacing: nearest neighbour, mounted troops EXCLUDED")
    for tag, name in (("Ii", "inv"), ("Dd", "def")):
        meds, ns = [], []
        for t in ts:
            vs = veh.get(t, [])
            pts = [(e[0], e[1]) for e in sol[t].values() if e[2] in tag and e[4] != 1]
            if vs:
                pts = [p for p in pts if min(math.dist(p, v[:2]) for v in vs) > 4]
            if len(pts) < 10:
                continue
            nn = [min(math.dist(p, q) for j, q in enumerate(pts) if j != i)
                  for i, p in enumerate(pts)]
            meds.append(st.median(nn)); ns.append(len(pts))
        if meds:
            print(f"   {name}: median NN {st.median(meds):5.1f} m over {len(meds)} frames"
                  f" (median {int(st.median(ns))} men/frame)")
        else:
            print(f"   {name}: too few dismounted men in any frame to measure")
    return 0


if __name__ == "__main__":
    sys.exit(main())
