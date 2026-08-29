#!/usr/bin/env python3
"""Analyse one Easy Red 2 play-test run of the Realistic mod.

WHY THIS EXISTS: a decision in the log is NOT proof of behaviour. A soldier can log
ROAD-MARCH every tick and never move (this happened to 36 soldiers, and only position
analysis exposed it). So this tool always cross-tabulates the ORDER against actual
DISPLACEMENT, and flags orders that did not produce the movement they imply.

Usage
  analyse_run.py [--log PATH] [--from-line N] [--json]
                 [--max-gap S] [--min-pooled S]

  --from-line N   only consider lines at/after N (mark the log before a run:
                  wc -l < Player.log)
  --max-gap S     ignore a sample pair separated by more than S seconds (default 30)
  --min-pooled S  a (soldier, label) pair needs at least S pooled seconds to count
                  (default 15)
  --json          machine-readable output

Trace line format produced by Realistic.lua (VERBOSE or sampled):
  [REALISTIC] #<uid> <nation>/<role> [ab=N ]@(<x>,<z>) ne=N nec=N nf=N ed=N fr=N.NN -> LABEL  | detail
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import re
import statistics
import sys

DEFAULT_LOG = os.path.expanduser("~/.config/unity3d/Corvostudio/Easy Red 2/Player.log")

TRACE = re.compile(
    r"\[REALISTIC\]\s+#(?P<uid>-?\d+)\s+(?:t=(?P<t>[\d.]+)\s+)?"
    r"(?P<nation>\w+)/(?P<role>[\w/-]+?)\s+"
    r"(?:ab=(?P<ab>\d)\s+)?@\((?P<x>-?\d+),(?P<z>-?\d+)\)\s+"
    r"ne=(?P<ne>\d+)\s+nec=(?P<nec>\d+)\s+nf=(?P<nf>\d+)\s+"
    r"ed=(?P<ed>-?\d+)\s+fr=(?P<fr>[\d.]+)\s+->\s+(?P<label>[A-Za-z/-]+)"
    r"(?:.*?obj d=(?P<objd>\d+))?"
)
LIFECYCLE = re.compile(r"\[REALISTIC\]\s+(ONLINE|OFFLINE)\s+#(-?\d+)")
ERRORS = re.compile(
    r"Lua error|guard\(once\)|not allowed as global variable|cannot access field|"
    r"Error in callback function|NullReferenceException"
)

# Which labels are an order to MOVE, and which are an order to HOLD. This mapping is the
# core of the check: a move-order that produces no displacement is a defect.
MOVE_ORDERS = {
    "ROAD-MARCH", "RALLY-on-MG", "ASSAULT", "MEDIC-sortie", "DRAG-approach",
    "BOUND-move", "ADVANCE-behind-armour", "ROUT", "RETURN-to-transport",
}
HOLD_ORDERS = {
    "DRAG-pickup", "DRAG-abandon", "REBOARD-transport",
}
# Cover-seeking orders. `findCover` is a VOID COMMAND whose entire purpose is to RELOCATE the
# soldier to a cover position (Realistic.lua: "findCover is a command; it moves us into cover").
# Displacement under these labels is therefore CORRECT behaviour, and no speed threshold can
# judge them: a man sprinting to a wall and a man refusing to move both read as "wrong" against
# one of the two thresholds. Reported for information, never gated.
#
# This set is DERIVED FROM THE CODE, not written by hand. For each label, look at the branch that
# assigns it and see which command it actually ends in: takeCover -> COVER, orderMove -> MOVE,
# stop/carryBody -> HOLD, releaseToBaseAI -> EXEMPT. Hand-maintaining it went wrong twice - first
# classifying PINNED/FIGHT-from-cover/LEADER-cover/MEDIC-hold-cover/DEFEND-hold as holds (they
# failed as a group, which is what exposed it), then filing AT-stalk and BOUND-move-cover as
# moves and AT-hunt/BOUND-overwatch/CREW-onfoot/RADIO-fire-mission as holds when every one of
# them ends in takeCover. Re-derive this list whenever a branch changes its terminal command.
COVER_ORDERS = {
    "PINNED", "FIGHT-from-cover", "LEADER-cover", "MEDIC-hold-cover", "DEFEND-hold",
    "SUPPORT-hold-fire", "ROUT-cover", "ASSAULT-cover",
    "AT-stalk", "AT-hunt",
    "BOUND-move-cover", "BOUND-overwatch",
    "CREW-onfoot", "RADIO-fire-mission", "DRAG-to-cover", "CONSOLIDATE",
}
EXEMPT_ORDERS = {
    "MOUNTED/CREW-defer", "ADVANCE-baseAI",
}
# Thresholds are in METRES PER SECOND, measured with the mission clock (t=) rather than the
# sample index, and attributed only to the order that was active while the movement happened.
#
# HOW SPEED IS MEASURED — pooled, not segmented.
# For every (soldier, label) pair we walk that soldier's samples in time order and accumulate
# each consecutive sample pair whose EARLIER sample carried the label:
#     pooled_dist += dist(p_i, p_i+1);  pooled_time += t_i+1 - t_i
# then speed = pooled_dist / pooled_time, and a label's figure is the MEDIAN over soldiers.
#
# Three traps this avoids, all hit for real while building this tool:
#  1. Whole-run displacement attributed to a soldier's "dominant" label is misleading: a man who
#     rode a truck 600 m and later took cover would have that mileage counted against the cover
#     order. Hence per-label attribution.
#  2. Sample index is NOT a clock. With VERBOSE=false the trace is throttled and repeats are
#     suppressed, so consecutive lines can be many seconds apart. Speed must come from t=;
#     samples without t= cannot be used and are dropped rather than guessed at.
#  3. CONTIGUOUS-SEGMENT measurement (the previous method) systematically UNDER-measures speed.
#     A soldier is sampled about once every 7 s while his label flips often, so most contiguous
#     same-label runs are 1-2 samples long; requiring >=3 samples threw away nearly all the
#     evidence and what survived was dominated by sampling noise. Real proof: soldiers whose
#     whole-trace displacement was 0.6-1.4 m/s were scored ROAD-MARCH 0.30 m/s over 4 segments
#     while the objective trend said "closing 4 | away 0". Pooling every qualifying pair per
#     (soldier, label) uses all the evidence instead of the accidentally-contiguous slivers.
MOVE_SPEED_MIN = 0.8     # m/s — a move-order should beat this (a walking man is ~2-4 m/s)
HOLD_SPEED_MAX = 0.5     # m/s — a hold-order should stay under this
MAX_GAP = 30.0           # s; a longer gap between samples means the soldier went untraced,
                         # so pinning that displacement on the earlier label is unsound — skip
MIN_POOLED_TIME = 15.0   # s; a (soldier, label) pair with less pooled time than this is not
                         # a measurement, it is noise — it does not contribute at all
MIN_SOLDIERS = 3         # contributing soldiers a label needs before the gate may judge it;
                         # below this the row prints but is INSUFFICIENT DATA and cannot fail

# Features expected to appear at all (from realistic.md §6.2). Absence = investigate.
EXPECTED_LABELS = sorted(MOVE_ORDERS | HOLD_ORDERS | COVER_ORDERS | EXEMPT_ORDERS)


def load(path: str, from_line: int):
    tracks: dict[str, list[dict]] = collections.defaultdict(list)
    labels = collections.Counter()
    errors = collections.Counter()
    online = set()
    offline = set()
    events = collections.Counter()
    total = 0
    with open(path, errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            if n < from_line:
                continue
            total += 1
            if "[EVENTS]" in line:
                m = re.search(r"\[EVENTS\]\s+(.*)", line)
                if m:
                    events[re.sub(r"-?\d+(\.\d+)?", "N", m.group(1).strip())[:110]] += 1
            if ERRORS.search(line):
                key = "guard(once)" if "guard(once)" in line else \
                      "callback error" if "Error in callback" in line else \
                      "UserData global" if "not allowed as global" in line else \
                      "NullReference" if "NullReferenceException" in line else "Lua error"
                errors[key] += 1
            lc = LIFECYCLE.search(line)
            if lc:
                (online if lc.group(1) == "ONLINE" else offline).add(lc.group(2))
            m = TRACE.search(line)
            if not m:
                continue
            d = m.groupdict()
            labels[d["label"]] += 1
            tracks[d["uid"]].append({
                "x": int(d["x"]), "z": int(d["z"]), "label": d["label"],
                "nation": d["nation"], "role": d["role"],
                "ne": int(d["ne"]), "nec": int(d["nec"]), "nf": int(d["nf"]),
                "fr": float(d["fr"]), "ab": d["ab"],
                "t": float(d["t"]) if d.get("t") else None,
                "objd": int(d["objd"]) if d["objd"] else None,
            })
    return tracks, labels, errors, online, offline, events, total


def displacement(pts):
    path = sum(math.dist((pts[i]["x"], pts[i]["z"]), (pts[i + 1]["x"], pts[i + 1]["z"]))
               for i in range(len(pts) - 1))
    net = math.dist((pts[0]["x"], pts[0]["z"]), (pts[-1]["x"], pts[-1]["z"]))
    return path, net


def pool_one_soldier(pts, max_gap):
    """Pool distance and time per label for ONE soldier.

    Walks the soldier's timed samples in time order and charges each consecutive pair to the
    label carried by the EARLIER sample — that is the order that was in force while the man
    covered that ground. Returns {label: [pooled_dist_m, pooled_time_s]}.

    Two pairs are refused:
      * dt <= 0  — log lines from the same tick can interleave, so ordering ties exist;
      * dt > max_gap — the soldier stopped being traced, and crediting a whole untraced
        stretch of movement to the last label seen before it is not a measurement.
    """
    timed = sorted((p for p in pts if p["t"] is not None), key=lambda p: p["t"])
    acc: dict[str, list[float]] = collections.defaultdict(lambda: [0.0, 0.0])
    for a, b in zip(timed, timed[1:]):
        dt = b["t"] - a["t"]
        if dt <= 0 or dt > max_gap:
            continue
        cell = acc[a["label"]]
        cell[0] += math.dist((a["x"], a["z"]), (b["x"], b["z"]))
        cell[1] += dt
    return acc


def pooled_speeds(tracks, max_gap, min_pooled):
    """Per-label list of per-soldier pooled speeds, plus the evidence behind each label.

    One soldier contributes AT MOST ONE speed per label, so a single hyperactive (or frozen)
    man cannot swing a label — the caller takes the median across soldiers.

    Returns (speeds, pooled_s, dropped, dropped_total) where
      speeds[label]   -> [m/s per contributing soldier]
      pooled_s[label] -> total pooled seconds behind the contributing soldiers
      dropped[label]  -> (soldier, label) pairs discarded for having < min_pooled seconds
    """
    speeds: dict[str, list[float]] = collections.defaultdict(list)
    pooled_s: dict[str, float] = collections.defaultdict(float)
    dropped: dict[str, int] = collections.Counter()
    dropped_total = 0
    for pts in tracks.values():
        for label, (dist, secs) in pool_one_soldier(pts, max_gap).items():
            if secs < min_pooled:
                dropped[label] += 1
                dropped_total += 1
                continue
            speeds[label].append(dist / secs)
            pooled_s[label] += secs
    return speeds, pooled_s, dropped, dropped_total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--from-line", type=int, default=1)
    ap.add_argument("--min-samples", type=int, default=4,
                    help="soldiers with fewer trace samples are excluded from movement stats")
    ap.add_argument("--max-gap", type=float, default=MAX_GAP,
                    help="seconds; sample pairs further apart than this are not measurable "
                         "(default %.0f)" % MAX_GAP)
    ap.add_argument("--min-pooled", type=float, default=MIN_POOLED_TIME,
                    help="seconds; a (soldier, label) pair needs at least this much pooled "
                         "time to contribute (default %.0f)" % MIN_POOLED_TIME)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(a.log):
        print("no log at %s" % a.log)
        return 2

    tracks, labels, errors, online, offline, events, total = load(a.log, a.from_line)

    rows = []
    for uid, pts in tracks.items():
        if len(pts) < a.min_samples:
            continue
        path, net = displacement(pts)
        dom = collections.Counter(p["label"] for p in pts).most_common(1)[0][0]
        rows.append({"uid": uid, "path": path, "net": net, "dom": dom,
                     "nation": pts[0]["nation"], "role": pts[0]["role"],
                     "ab": pts[0]["ab"], "n": len(pts)})

    # Pooled: attribute movement only to the order active while it happened, but pool ALL of a
    # soldier's time under that order instead of only the accidentally-contiguous slivers.
    by_order, pooled_s, dropped, dropped_total = pooled_speeds(tracks, a.max_gap, a.min_pooled)

    verdicts = {}
    for label in sorted(set(labels) | set(by_order)):
        speeds = by_order.get(label, [])
        n_sold = len(speeds)
        # still % = share of CONTRIBUTING SOLDIERS whose pooled speed is at or below the hold
        # threshold. It is a count of men, not of samples.
        med = statistics.median(speeds) if speeds else None
        still = (sum(1 for s in speeds if s <= HOLD_SPEED_MAX) / n_sold * 100) if n_sold else None
        if label in EXEMPT_ORDERS:
            ok = True
            verdict = "EXEMPT (base AI by design)"
        elif label in COVER_ORDERS:
            # findCover relocates the man; neither threshold applies. Report, never gate.
            ok = True
            verdict = "COVER-SEEK (findCover relocates; not gated)"
        elif n_sold < MIN_SOLDIERS:
            # Too few men measured to say anything. An under-sampled label must never fail the
            # gate — that mistake is the whole reason this tool was rewritten.
            ok = None
            verdict = "INSUFFICIENT DATA (n<%d)" % MIN_SOLDIERS
        elif label in MOVE_ORDERS:
            ok = med >= MOVE_SPEED_MIN
            verdict = "OK moving" if ok else ("WEAK" if med > HOLD_SPEED_MAX else "!! NOT MOVING")
        elif label in HOLD_ORDERS:
            ok = med <= HOLD_SPEED_MAX
            verdict = "OK holding" if ok else "MOVING (base AI / in vehicle?)"
        else:
            ok, verdict = None, "unknown label"
        verdicts[label] = {"soldiers": n_sold, "pooled_s": pooled_s.get(label, 0.0),
                           "median_m_per_s": med, "still_pct": still,
                           "dropped_short_pairs": dropped.get(label, 0),
                           "ok": ok, "verdict": verdict}

    # objective-distance trend for road-marchers
    closing = opening = flat = 0
    for uid, pts in tracks.items():
        ds = [p["objd"] for p in pts if p["label"] == "ROAD-MARCH" and p["objd"] is not None]
        if len(ds) >= 3:
            if ds[-1] < ds[0] - 5:
                closing += 1
            elif ds[-1] > ds[0] + 5:
                opening += 1
            else:
                flat += 1

    missing = [l for l in EXPECTED_LABELS if l not in labels]
    ab_groups = collections.Counter(r["ab"] for r in rows if r["ab"] is not None)

    result = {
        "log": a.log, "from_line": a.from_line, "lines_scanned": total,
        "traced_soldiers": len(tracks), "soldiers_in_stats": len(rows),
        "online": len(online), "offline": len(offline),
        "errors": dict(errors), "decisions": dict(labels.most_common()),
        "per_order": verdicts,
        "speed_method": {
            "pooling": "per (soldier, label); median across soldiers",
            "max_gap_s": a.max_gap, "min_pooled_s": a.min_pooled,
            "min_soldiers": MIN_SOLDIERS,
            "move_speed_min": MOVE_SPEED_MIN, "hold_speed_max": HOLD_SPEED_MAX,
            "pairs_dropped_below_min_pooled": dropped_total,
            "labels_insufficient_data": sorted(
                l for l, v in verdicts.items()
                if v["soldiers"] < MIN_SOLDIERS
                and l not in EXEMPT_ORDERS and l not in COVER_ORDERS),
        },
        "road_march_trend": {"closing": closing, "away": opening, "flat": flat},
        "labels_absent": missing,
        "ab_groups": dict(ab_groups),
        "move_orders": sorted(MOVE_ORDERS),
        "hold_orders": sorted(HOLD_ORDERS),
        "cover_orders": sorted(COVER_ORDERS),
        "exempt_orders": sorted(EXEMPT_ORDERS),
    }

    if a.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    print("=" * 78)
    print("ER2 Realistic — run analysis")
    print("  log %s (from line %d, %d lines scanned)" % (a.log, a.from_line, total))
    print("  soldiers traced %d  (%d with >=%d samples)  ONLINE %d  OFFLINE %d"
          % (len(tracks), len(rows), a.min_samples, len(online), len(offline)))
    print("=" * 78)

    print("\nERRORS  (gate: must be empty)")
    if errors:
        for k, v in errors.most_common():
            print("  !! %-20s %d" % (k, v))
    else:
        print("  none")

    print("\nDECISIONS")
    tot = sum(labels.values()) or 1
    for lbl, n in labels.most_common():
        print("  %-24s %6d  %5.1f%%" % (lbl, n, 100 * n / tot))

    print("\nDOES THE ORDER MATCH THE BEHAVIOUR?")
    print("  (per soldier, all time under that order is pooled into one distance/time;"
          " the figure")
    print("   below is the MEDIAN of those per-soldier speeds."
          "  move >= %.1f, hold <= %.1f m/s)" % (MOVE_SPEED_MIN, HOLD_SPEED_MAX))
    print("  pooled_s = total measured seconds behind the row; a label needs >=%d soldiers"
          % MIN_SOLDIERS)
    print("  before the gate may judge it.  still % = share of CONTRIBUTING SOLDIERS whose")
    print("  pooled speed is <= %.1f m/s (men, not samples)."
          "  gap >%.0fs or pooled <%.0fs is dropped."
          % (HOLD_SPEED_MAX, a.max_gap, a.min_pooled))
    print("  %-24s %8s %12s %9s %7s   %s"
          % ("order", "soldiers", "median m/s", "pooled_s", "still", "verdict"))
    for dom, v in sorted(verdicts.items(),
                         key=lambda kv: (-kv[1]["soldiers"], -kv[1]["pooled_s"])):
        flag = " " if v["ok"] is not False else "!"
        med = "%12.2f" % v["median_m_per_s"] if v["median_m_per_s"] is not None else "%12s" % "-"
        still = "%6.0f%%" % v["still_pct"] if v["still_pct"] is not None else "%7s" % "-"
        print("%s %-24s %8d %s %9.1f %s   %s"
              % (flag, dom, v["soldiers"], med, v["pooled_s"], still, v["verdict"]))
    thin = [l for l, v in verdicts.items()
            if v["ok"] is None and v["verdict"].startswith("INSUFFICIENT")]
    print("  %d (soldier,label) pairs dropped for < %.0fs pooled time; "
          "%d label(s) INSUFFICIENT DATA (excluded from the gate)"
          % (dropped_total, a.min_pooled, len(thin)))

    print("\nROAD-MARCH objective trend:  closing %d | away %d | no change %d"
          % (closing, opening, flat))

    if ab_groups:
        print("\nA/B groups: %s" % dict(ab_groups))
        for g in sorted(ab_groups):
            rs = [r for r in rows if r["ab"] == g]
            print("  ab=%s n=%d median path=%.1fm"
                  % (g, len(rs), statistics.median(r["path"] for r in rs)))

    if missing:
        print("\nLABELS NEVER SEEN (unreachable branch, or scenario-dependent):")
        for l in missing:
            print("  - %s" % l)

    print("\nTOP [EVENTS] SHAPES")
    for shape, n in events.most_common(12):
        print("  %5d  %s" % (n, shape))

    bad = [d for d, v in verdicts.items() if v["ok"] is False
           and d not in EXEMPT_ORDERS and d not in COVER_ORDERS]
    print("\n" + "=" * 78)
    if errors or bad:
        print("GATE: FAIL — %s%s" % ("errors present. " if errors else "",
                                     ("orders not matching behaviour: " + ", ".join(bad)) if bad else ""))
        return 1
    print("GATE: PASS — no errors; every order class behaved as its class implies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
