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
                        veh[t].append((int(p[1]), int(p[3])))
                    elif len(p) >= 4:
                        veh[t].append((int(p[1]), int(p[2])))
                except (ValueError, IndexError):
                    pass
    return sol, veh


def side_of(flag):
    return "inv" if flag in "Ii" else ("def" if flag in "Dd" else "down")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", nargs="?", default=os.path.expanduser(
        "~/.config/unity3d/Corvostudio/Easy Red 2/Player.log"))
    a = ap.parse_args()

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
            if e[4] == 1 or (e[4] == -1 and vs and min(math.dist((x, z), v) for v in vs) <= 4):
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

    # ---- 5b : formation PER SQUAD - the only direct test of the staggered file
    # A section in file spreads ALONG its axis of march and stays narrow ACROSS it. A blob spreads
    # equally both ways. Measuring the whole force instead just reports army frontage, which swamps
    # the few metres that separate two files of one section.
    print("\n--- formation PER SQUAD (dismounted, moving, >=3 men in the squad)")
    lat, lon, ratio = [], [], []
    for i in range(1, len(ts)):
        t0, t1 = ts[i - 1], ts[i]
        vs = veh.get(t1, [])
        squads = {}
        for uid, e in sol[t1].items():
            x, z, f, sq = e[0], e[1], e[2], (e[3] if len(e) > 3 else 0)
            if sq == 0 or side_of(f) != "inv":
                continue
            prev = sol[t0].get(uid)
            if not prev:
                continue
            d = math.dist((prev[0], prev[1]), (x, z))
            if d < 1.0 or d > 40:
                continue
            if e[4] == 1 or (e[4] == -1 and vs and min(math.dist((x, z), v) for v in vs) <= 4):
                continue
            squads.setdefault(sq, []).append(((x, z), ((x - prev[0]) / d, (z - prev[1]) / d)))
        for sq, pts in squads.items():
            if len(pts) < 3:
                continue
            hx = st.mean(p[1][0] for p in pts); hz = st.mean(p[1][1] for p in pts)
            n = math.hypot(hx, hz)
            if n < 0.3:
                continue
            hx, hz = hx / n, hz / n
            px, pz = -hz, hx
            across = [p[0][0] * px + p[0][1] * pz for p in pts]
            along  = [p[0][0] * hx + p[0][1] * hz for p in pts]
            a = st.pstdev(across) if len(across) > 1 else 0
            b = st.pstdev(along) if len(along) > 1 else 0
            lat.append(a); lon.append(b)
            if a > 0.01:
                ratio.append(b / a)
    if lat:
        print(f"   squad-frames measured {len(lat)}")
        print(f"   ACROSS the axis (should be small): median {st.median(lat):5.1f} m")
        print(f"   ALONG  the axis (should be larger): median {st.median(lon):5.1f} m")
        if ratio:
            print(f"   along/across ratio: median {st.median(ratio):.2f}"
                  f"   ( >1 = strung out in file, ~1 = a blob )")
    else:
        print("   no squad had 3+ dismounted movers in a frame - cannot measure")

    # ---- 6 : spacing, mounted excluded
    print("\n--- spacing: nearest neighbour, mounted troops EXCLUDED")
    for tag, name in (("Ii", "inv"), ("Dd", "def")):
        meds, ns = [], []
        for t in ts:
            vs = veh.get(t, [])
            pts = [(e[0], e[1]) for e in sol[t].values() if e[2] in tag and e[4] != 1]
            if vs:
                pts = [p for p in pts if min(math.dist(p, v) for v in vs) > 4]
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
