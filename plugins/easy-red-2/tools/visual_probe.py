#!/usr/bin/env python3
"""Repeatable visual probing of a live Easy Red 2 session.

WHY THIS EXISTS: visual verification kept being hand-piloted, and hand-piloting produced two
failure modes that both cost whole sessions.

  1. ABSOLUTE POINTER WARPS DO NOT TURN ER2'S FREE CAMERA. Three separate DRAG attempts
     returned pixel-identical frames before this was diagnosed: the camera reads RAW RELATIVE
     motion, so only MOVE_REL / LOOK move the view. Every sweep here goes through LOOK.
  2. A CAPTURED FRAME IS NOT EVIDENCE. Several "verification" screenshots turned out to be
     featureless sand — nothing in them at all. `contrast` scores a frame so an empty one is
     REJECTED automatically instead of eyeballed.

Usage
  visual_probe.py shot [--out PATH]
  visual_probe.py look --dx D --dy D [--steps N] [--delay MS] [--button B] [--out PATH]
  visual_probe.py orbit --shots N [--dy PITCH] [--outdir DIR]
  visual_probe.py ascend --steps N [--out PATH]
  visual_probe.py contrast PATH [--json]

The socket and its protocol are NOT reimplemented here: hsend() is imported from the MCP
server, so there is exactly one definition of how to talk to the harness.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import struct
import sys
import time
import zlib

# server.py is not an importable package (no __init__.py) and must not be executed as __main__,
# so load it by path. Its module-level code is import-safe: it only resolves paths.
_SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "er2_mcp", "server.py")
_spec = importlib.util.spec_from_file_location("er2_mcp_server", _SERVER)
_srv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_srv)

hsend = _srv.hsend
HarnessError = _srv.HarnessError
VK = _srv.VK

DEFAULT_DIR = os.path.join(_srv.TMP, "visual")

# A full turn measured against the harness sweep unit. LOOK deltas are raw mouse counts, and
# ER2 at default sensitivity yaws ~1 degree per 10 counts, so 360 degrees is 3600 counts.
YAW_PER_TURN = 3600.0

# The ER2 Free Camera "up" binding is the E key (VK 0x45), which server.py already maps.
ASCEND_VK = VK["e"]


# ------------------------------------------------------------------ capture
def capture(path):
    """Grab one frame to `path`. Raises on anything that is not a real, written file."""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    reply = hsend(["SCREENSHOT %s" % path])[0]
    if not reply.startswith("OK"):
        raise HarnessError("SCREENSHOT refused: %s" % reply)
    if not os.path.exists(path):
        raise HarnessError("SCREENSHOT said %s but wrote no file at %s" % (reply, path))
    return path


def sweep(dx, dy, steps=20, delay_ms=8, button=None):
    """One free-look sweep. Relative motion only — see the module docstring."""
    look = "LOOK %g %g %d %d" % (dx, dy, steps, delay_ms)
    cmds = [look] if button is None else \
        ["BUTTON DOWN %d" % button, look, "BUTTON UP %d" % button]
    return hsend(cmds)


# ------------------------------------------------------------------ PNG stats
def _png_rows(path):
    """Decode a PNG to (width, height, [bytes-per-row of RGB(A)/grey samples], channels, depth).

    Hand-rolled because the repo carries NO third-party dependencies (see analyse_run.py,
    battle_map.py: stdlib only) and adding Pillow for a mean and a stddev is not worth it.
    Supports the non-interlaced 8/16-bit truecolour and greyscale forms the harness emits.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("%s is not a PNG" % path)
    pos, idat, hdr = 8, [], None
    while pos + 8 <= len(data):
        (ln,) = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            hdr = struct.unpack(">IIBBBBB", body)
        elif typ == b"IDAT":
            idat.append(body)
        elif typ == b"IEND":
            break
        pos += 12 + ln
    if hdr is None:
        raise ValueError("%s has no IHDR" % path)
    w, h, depth, ctype, comp, filt, interlace = hdr
    if interlace:
        raise ValueError("interlaced PNG is not supported")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None or ctype == 3:
        raise ValueError("unsupported PNG colour type %d" % ctype)
    bpp = max(1, channels * depth // 8)
    stride = (w * channels * depth + 7) // 8
    raw = zlib.decompress(b"".join(idat))

    out, prev, p = [], bytearray(stride), 0
    for _ in range(h):
        ft = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        # Undo the per-scanline filter (PNG spec 9.2); each is defined against the
        # reconstructed bytes, so this must run in order.
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            x = line[i]
            if ft == 1:
                x += a
            elif ft == 2:
                x += b
            elif ft == 3:
                x += (a + b) >> 1
            elif ft == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                x += a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            line[i] = x & 0xFF
        out.append(bytes(line))
        prev = line
    return w, h, out, channels, depth


def frame_stats(path, sample=4):
    """Luminance mean/stddev and unique-colour fraction for one frame.

    `sample` decimates by taking every Nth pixel in each axis — a 1920x1080 frame is 2M
    pixels and pure-Python per-pixel work over all of them is slow enough to discourage use.
    """
    w, h, rows, channels, depth = _png_rows(path)
    step = max(1, int(sample))
    psize = channels * depth // 8
    off = depth // 8 - 1 if depth == 16 else 0   # take the high byte of 16-bit samples

    total = sq = n = 0
    colours = set()
    for y in range(0, h, step):
        row = rows[y]
        for x in range(0, w, step):
            i = x * psize
            if channels >= 3:
                r, g, b = row[i + off], row[i + psize // channels + off], \
                    row[i + 2 * (psize // channels) + off]
            else:
                r = g = b = row[i + off]
            # Rec. 601 luma, integer-weighted; exact coefficients do not matter for a
            # "is this frame empty" test, consistency across frames does.
            lum = (299 * r + 587 * g + 114 * b) // 1000
            total += lum
            sq += lum * lum
            n += 1
            colours.add((r, g, b))

    mean = total / n
    var = max(0.0, sq / n - mean * mean)
    return {
        "path": os.path.abspath(path),
        "width": w, "height": h, "sampled": n,
        "mean": round(mean, 3),
        "stddev": round(var ** 0.5, 3),
        "unique_colours": len(colours),
        "unique_fraction": round(len(colours) / n, 5),
    }


# A frame this flat is featureless ground, a loading fade, or a blank surface. These thresholds
# were set against real rejected captures: empty sand scored stddev ~4 and unique_fraction
# ~0.004, while a frame with soldiers, vehicles or a horizon in it clears both comfortably.
MIN_STDDEV = 12.0
MIN_UNIQUE_FRACTION = 0.02


def verdict(st):
    """(ok, reason) — is this frame usable as visual evidence?"""
    why = []
    if st["stddev"] < MIN_STDDEV:
        why.append("stddev %.1f < %.1f (flat, no structure)" % (st["stddev"], MIN_STDDEV))
    if st["unique_fraction"] < MIN_UNIQUE_FRACTION:
        why.append("unique colour fraction %.4f < %.4f (one material fills the frame)"
                   % (st["unique_fraction"], MIN_UNIQUE_FRACTION))
    return (not why), "; ".join(why) or "has structure and colour variety"


def _report(path):
    st = frame_stats(path)
    ok, why = verdict(st)
    print("%-8s %s" % ("USABLE" if ok else "EMPTY", st["path"]))
    print("  %dx%d  mean=%.1f  stddev=%.1f  unique=%d (%.4f of sampled)"
          % (st["width"], st["height"], st["mean"], st["stddev"],
             st["unique_colours"], st["unique_fraction"]))
    print("  %s" % why)
    return st, ok


# ------------------------------------------------------------------ subcommands
def cmd_shot(a):
    p = capture(a.out or os.path.join(DEFAULT_DIR, "shot.png"))
    _report(p)
    return 0


def cmd_look(a):
    print("; ".join(sweep(a.dx, a.dy, a.steps, a.delay, a.button)))
    time.sleep(0.3)
    p = capture(a.out or os.path.join(DEFAULT_DIR, "look.png"))
    _report(p)
    return 0


def cmd_orbit(a):
    outdir = a.outdir or DEFAULT_DIR
    per = YAW_PER_TURN / a.shots
    usable = 0
    if a.dy:
        # Pitch once up front so every frame of the panorama shares one horizon line.
        sweep(0.0, a.dy, a.steps, a.delay, a.button)
        time.sleep(0.3)
    for i in range(a.shots):
        p = capture(os.path.join(outdir, "orbit_%02d.png" % i))
        st, ok = _report(p)
        usable += ok
        if i < a.shots - 1:
            sweep(per, 0.0, a.steps, a.delay, a.button)
            time.sleep(0.3)
    print("\n%d/%d frames usable across a full 360 (%.0f yaw units per step)"
          % (usable, a.shots, per))
    return 0 if usable else 1


def cmd_ascend(a):
    # E is the Free Camera "up" binding; one tap per step so altitude is repeatable.
    replies = hsend(["KEY %#04x" % ASCEND_VK] * a.steps)
    bad = [r for r in replies if not r.startswith("OK")]
    print("sent %d E taps (%s)" % (a.steps, "all OK" if not bad else "; ".join(bad)))
    time.sleep(0.5)
    p = capture(a.out or os.path.join(DEFAULT_DIR, "ascend.png"))
    _report(p)
    return 0


def cmd_contrast(a):
    st = frame_stats(a.path)
    ok, why = verdict(st)
    if a.json:
        print(json.dumps(dict(st, usable=ok, reason=why), indent=2))
    else:
        _report(a.path)
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("shot", help="capture one frame and score it")
    s.add_argument("--out", help="output PNG (default %s/shot.png)" % DEFAULT_DIR)
    s.set_defaults(fn=cmd_shot)

    s = sub.add_parser("look", help="free-look sweep, then capture")
    s.add_argument("--dx", type=float, required=True, help="yaw sweep, + = right")
    s.add_argument("--dy", type=float, default=0.0, help="pitch sweep, + = down")
    s.add_argument("--steps", type=int, default=20, help="motions per sweep (default 20)")
    s.add_argument("--delay", type=int, default=8, help="ms between motions (default 8)")
    s.add_argument("--button", type=int, help="hold this mouse button for the sweep")
    s.add_argument("--out", help="output PNG")
    s.set_defaults(fn=cmd_look)

    s = sub.add_parser("orbit", help="N frames sweeping a full 360 degrees -> a panorama")
    s.add_argument("--shots", type=int, required=True, help="frames in the turn")
    s.add_argument("--dy", type=float, default=0.0,
                   help="one-off pitch applied before the first frame (+ = look down)")
    s.add_argument("--steps", type=int, default=20)
    s.add_argument("--delay", type=int, default=8)
    s.add_argument("--button", type=int, help="hold this mouse button while sweeping")
    s.add_argument("--outdir", help="directory for orbit_NN.png (default %s)" % DEFAULT_DIR)
    s.set_defaults(fn=cmd_orbit)

    s = sub.add_parser("ascend", help="raise the free camera (E key), then capture")
    s.add_argument("--steps", type=int, required=True, help="number of E taps")
    s.add_argument("--out", help="output PNG")
    s.set_defaults(fn=cmd_ascend)

    s = sub.add_parser("contrast", help="score a captured frame; exit 1 if it is visually empty")
    s.add_argument("path")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.set_defaults(fn=cmd_contrast)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (HarnessError, ValueError, OSError) as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
