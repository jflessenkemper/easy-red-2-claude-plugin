#!/usr/bin/env python3
"""Record the game to a video clip AND a contact sheet.

Why both
--------
Stills sampled every few seconds miss anything temporal -- a 45-second diorama
reset, a medic crossing to a casualty, a squad bounding. A clip captures the
motion; the contact sheet is how an AGENT reads that motion, since a model can
look at one tiled image but cannot watch an mp4.

Frame rate
----------
Capture cost is proportional to PIXEL AREA, measured 2026-09-13:

    full frame 1920x1080   ~660 ms   ->  1.5 fps
    region       640x360    ~69 ms   -> 14   fps
    PIXEL                     5 ms
    STATE                    ~0 ms

So the bottleneck is per-pixel readback -- not the socket round-trip, and not the
encoder (PNG measured FASTER than JPEG). `--region X,Y,W,H` is therefore the main
lever for smooth video without relaunching the harness smaller. NOTE the harness
demands a .png path for regions, so region capture is always PNG.

x11grab on the nested Xwayland does NOT work: the game renders through gamescope's
compositor, so the X root window is solid black (verified -- mean 0.0). The
compositor screenshot path is the only real pixel source. Also beware DISPLAY=:0
in the game's environment: that is the USER'S OWN 2560x1440 desktop, inherited
from the host. Capturing it would record their screen.

Usage
  record.py clip --seconds 45 --fps 4 --name reset
  record.py clip --seconds 45 --fps 4 --name reset --wait-log "round .* over"
  record.py sheet --name reset --cols 6          # rebuild the sheet only
"""

import argparse
import os
import re
import socket
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
SOCK = os.environ.get("ER2_HARNESS_SOCK") or os.path.join(HOME, ".er2harness.sock")
OUT = os.environ.get("ER2_TMP") or "/tmp/er2_mcp"
LOG = os.path.join(HOME, ".config/unity3d/Corvostudio/Easy Red 2/Player.log")


def connect():
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(20)
    s.connect(SOCK)
    return s


def read_line(f):
    return f.readline().decode("utf-8", "replace").strip()


def grab(f, fmt="jpg", region=None):
    """One frame. Returns raw encoded bytes, or None if the harness refused.

    Capture cost is almost PURELY proportional to pixel area -- measured on
    2026-09-13: a full 1920x1080 frame takes ~660 ms, a 640x360 region ~69 ms
    (9.0x fewer pixels, 9.6x faster), while PIXEL is 5 ms and STATE ~0 ms. So the
    bottleneck is per-pixel readback, not the socket round-trip and not the
    encoder (PNG actually measured FASTER than JPEG). Cropping to the action is
    the only way to raise the frame rate without relaunching the harness at a
    lower internal resolution.
    """
    if region:
        x, y, w, h = region
        path = os.path.join(OUT, "_regionframe.%s" % fmt)
        f.write(("SCREENSHOT_REGION %d %d %d %d %s\n" % (x, y, w, h, path)).encode())
        f.flush()
        if not read_line(f).startswith("OK"):
            return None
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except IOError:
            return None
    f.write(("SCREENSHOT_BYTES %s\n" % fmt).encode())
    f.flush()
    head = read_line(f)
    if not head.startswith("OK"):
        return None
    m = re.search(r"bytes=(\d+)", head)
    if not m:
        return None
    want = int(m.group(1))
    buf = b""
    while len(buf) < want:
        chunk = f.read(want - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf if len(buf) == want else None


def wait_for_log(pattern, timeout=180):
    """Block until a NEW line matching `pattern` appears. Returns the line.

    Waiting on the event rather than on wall-clock: the diorama paces itself and
    a fixed sleep has repeatedly captured the wrong window.
    """
    rx = re.compile(pattern)
    try:
        base = sum(1 for ln in open(LOG, errors="replace") if rx.search(ln))
    except IOError:
        print("no log at %s" % LOG, file=sys.stderr)
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        hits = [ln.strip() for ln in open(LOG, errors="replace") if rx.search(ln)]
        if len(hits) > base:
            return hits[-1]
        time.sleep(1.0)
    return None


def cmd_clip(args):
    d = os.path.join(OUT, "clips", args.name)
    os.makedirs(d, exist_ok=True)
    for old in os.listdir(d):
        if old.endswith((".jpg", ".png")):
            os.remove(os.path.join(d, old))

    if args.wait_log:
        line = wait_for_log(args.wait_log, args.wait_timeout)
        if line is None:
            print("TIMEOUT waiting for /%s/" % args.wait_log, file=sys.stderr)
            return 2
        print("trigger: %s" % line)

    region = None
    if args.region:
        # SCREENSHOT_REGION only accepts a .png path (ERR INVALID_REGION
        # must_have_png_extension), so region capture is PNG regardless of --fmt.
        args.fmt = "png"
        try:
            region = tuple(int(v) for v in args.region.split(","))
            assert len(region) == 4
        except (ValueError, AssertionError):
            print("bad --region, want X,Y,W,H", file=sys.stderr)
            return 2

    s = connect()
    f = s.makefile("rwb")
    period = 1.0 / args.fps
    n, t0, nxt = 0, time.time(), time.time()
    while time.time() - t0 < args.seconds:
        raw = grab(f, args.fmt, region)
        if raw:
            with open(os.path.join(d, "f%04d.%s" % (n, args.fmt)), "wb") as fh:
                fh.write(raw)
            n += 1
        nxt += period
        slack = nxt - time.time()
        if slack > 0:
            time.sleep(slack)
    dur = time.time() - t0
    print("captured %d frames in %.1fs (%.1f fps actual)" % (n, dur, n / dur if dur else 0))
    if not n:
        return 1

    make_video(d, args.name, args.fps, args.fmt)
    make_sheet(d, args.name, args.cols, args.fmt)
    return 0


def make_video(d, name, fps, fmt):
    out = os.path.join(OUT, "clips", "%s.mp4" % name)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
           "-i", os.path.join(d, "f%%04d.%s" % fmt),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "scale=min(960\\,iw):-2", out]
    try:
        subprocess.run(cmd, check=True)
        print("video: %s" % out)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print("video encode failed: %s" % exc, file=sys.stderr)


def make_sheet(d, name, cols, fmt):
    """Tile frames into one image, each labelled with its index.

    This is the artefact the agent actually reads -- motion becomes visible as
    difference across adjacent tiles.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("PIL missing, no contact sheet", file=sys.stderr)
        return
    files = sorted(f for f in os.listdir(d) if f.endswith("." + fmt))
    if not files:
        return
    # A sheet with more than ~24 tiles is unreadable; sample evenly.
    limit = 24
    if len(files) > limit:
        step = len(files) / float(limit)
        files = [files[int(i * step)] for i in range(limit)]
    tw = 420
    thumbs = []
    for fn in files:
        im = Image.open(os.path.join(d, fn)).convert("RGB")
        im = im.resize((tw, int(im.height * tw / im.width)))
        thumbs.append((fn, im))
    th = thumbs[0][1].height
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    for i, (fn, im) in enumerate(thumbs):
        x, y = (i % cols) * tw, (i // cols) * th
        sheet.paste(im, (x, y))
        label = fn.split(".")[0].replace("f", "")
        draw.rectangle([x + 2, y + 2, x + 46, y + 20], fill=(0, 0, 0))
        draw.text((x + 6, y + 6), label, fill=(255, 230, 0))
    out = os.path.join(OUT, "clips", "%s_sheet.png" % name)
    sheet.save(out)
    print("sheet: %s (%d tiles, %dx%d)" % (out, len(thumbs), sheet.width, sheet.height))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("clip", help="record frames, then build video + sheet")
    c.add_argument("--seconds", type=float, default=20.0)
    c.add_argument("--fps", type=float, default=30.0)  # evidence clips: 30 fps (2026-10-23)
    c.add_argument("--name", default="clip")
    c.add_argument("--cols", type=int, default=6)
    c.add_argument("--fmt", choices=["jpg", "png"], default="jpg")
    c.add_argument("--region", metavar="X,Y,W,H",
                   help="capture only this rectangle. Frame cost is proportional to "
                        "pixel AREA, so cropping is the main way to raise the frame "
                        "rate: full 1920x1080 ~660ms (1.5 fps), 640x360 ~69ms (14 fps).")
    c.add_argument("--wait-log", help="regex; start only when a NEW matching log line appears")
    c.add_argument("--wait-timeout", type=float, default=180.0)
    c.set_defaults(fn=cmd_clip)

    s = sub.add_parser("sheet", help="rebuild the contact sheet from saved frames")
    s.add_argument("--name", default="clip")
    s.add_argument("--cols", type=int, default=6)
    s.add_argument("--fmt", choices=["jpg", "png"], default="jpg")
    s.set_defaults(fn=lambda a: make_sheet(
        os.path.join(OUT, "clips", a.name), a.name, a.cols, a.fmt))

    args = ap.parse_args()
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
