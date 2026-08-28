#!/usr/bin/env python3
"""Set Steam Launch Options for Easy Red 2 so it starts inside the harness.

WHY: launching the game binary directly (with SteamAppId set) runs the base game, but the
process cannot see DLC entitlements — owned DLC missions still show "Needs DLCs: ...". Steam
only issues a proper app ticket through the %command% launch path, so the harness must wrap
%command% in Steam's own launch options.

SAFETY
  * Refuses to run while Steam is running (Steam holds an exclusive write lock on
    localconfig.vdf and will overwrite your edit on exit).
  * Dry-run by default: prints the diff and changes nothing. Pass --apply to write.
  * Backs up localconfig.vdf next to the original before writing.

USAGE
  python3 fix_steam_launch_options.py                 # show what would change
  python3 fix_steam_launch_options.py --apply         # write it
  python3 fix_steam_launch_options.py --apply --clear # remove the harness wrapper again
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import time

APPID = "1324780"  # Easy Red 2
HOME = os.path.expanduser("~")

HARNESS_CANDIDATES = [
    os.path.join(HOME, "AOE-3-DE-Harness/build-f44/src/AOE3DEHarness"),
    os.path.join(HOME, "AOE-3-DE-Harness/AOE3DEHarness-x86_64.AppImage"),
]

# Socket lives in $HOME, NOT /tmp. Steam launches the harness in a different mount
# namespace from tooling that may run sandboxed with a private /tmp — the socket then
# binds successfully (ss shows it LISTENing) but is invisible to the client, which looks
# like "harness not running". $HOME is shared by every party involved.
SOCKET = os.path.join(HOME, ".er2harness.sock")

FLAGS = ("--keep-alive -W 1920 -H 1080 -w 1920 -h 1080 -r 30 --framerate-limit 30 "
         "--backend headless --xwayland-count 1 --harness-socket %s" % SOCKET)


def steam_running() -> bool:
    try:
        out = subprocess.run(["ps", "-eo", "comm"], capture_output=True, text=True,
                             timeout=15).stdout.splitlines()
    except Exception:
        return False
    return any(c.strip() == "steam" for c in out)


def find_harness() -> str:
    path = None
    for p in HARNESS_CANDIDATES:
        if os.path.exists(p):
            path = p
            break
    path = path or shutil.which("AOE3DEHarness")
    if not path:
        sys.exit("ERROR: harness binary not found. Looked in:\n  " + "\n  ".join(HARNESS_CANDIDATES))
    if " " in path:
        # VDF can't quote, so a path with spaces can't go in LaunchOptions directly.
        # Emit a space-free shim and reference that instead.
        shim_dir = os.path.join(HOME, ".local", "bin")
        os.makedirs(shim_dir, exist_ok=True)
        shim = os.path.join(shim_dir, "er2-harness")
        with open(shim, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nexec "%s" "$@"\n' % path)
        os.chmod(shim, 0o755)
        print("NOTE: harness path contains spaces; created shim %s" % shim)
        return shim
    return path


def localconfigs() -> list[str]:
    pats = [
        os.path.join(HOME, ".local/share/Steam/userdata/*/config/localconfig.vdf"),
        os.path.join(HOME, ".steam/steam/userdata/*/config/localconfig.vdf"),
    ]
    out: list[str] = []
    for p in pats:
        out.extend(glob.glob(p))
    return out


def patch(text: str, appid: str, value: str) -> tuple[str, str | None]:
    """Set LaunchOptions inside the block for `appid`. Returns (new_text, old_value).

    NOTE: VDF has no string escaping. A value containing a double quote terminates the
    string early, which silently splits LaunchOptions into an empty value plus a bogus
    extra key — Steam then launches the game unwrapped. Never quote paths in `value`.
    """
    if '"' in value:
        sys.exit("INTERNAL ERROR: launch-options value must not contain double quotes "
                 "(VDF cannot escape them). Value was:\n  %s" % value)
    # find "<appid>" { ... } and operate only within that block. \s* spans the newline
    # before the brace, so this matches the real app-config block and not the hex blobs
    # under apptickets/nettickets that share the same appid key.
    m = re.search(r'("%s"\s*\{)' % re.escape(appid), text)
    if not m:
        return text, None
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    block = text[start:i]
    # Repair damage from an earlier buggy write: a quoted path became its own key line.
    block = re.sub(r'\n\s*"[^"\n]*AOE3DEHarness[^"\n]*"\s*"[^"\n]*"', "", block)
    lo = re.search(r'"LaunchOptions"\s*"([^"]*)"', block)
    old = lo.group(1) if lo else ""
    if value == "":
        new_block = re.sub(r'\n\s*"LaunchOptions"\s*"[^"]*"', "", block) if lo else block
    elif lo:
        new_block = block[:lo.start()] + '"LaunchOptions"\t\t"%s"' % value + block[lo.end():]
    else:
        new_block = "\n\t\t\t\t\t\"LaunchOptions\"\t\t\"%s\"" % value + block
    return text[:start] + new_block + text[i:], old


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write the change")
    ap.add_argument("--clear", action="store_true", help="remove the harness wrapper instead")
    a = ap.parse_args()

    if a.apply and steam_running():
        sys.exit("ERROR: Steam is running. Quit Steam fully first — it holds an exclusive write "
                 "lock on localconfig.vdf and will overwrite this edit on exit.")

    # Unquoted path — VDF cannot escape quotes (see patch()); find_harness() guarantees
    # the path is space-free, emitting a shim if necessary.
    value = "" if a.clear else "%s %s -- %%command%%" % (find_harness(), FLAGS)
    files = localconfigs()
    if not files:
        sys.exit("ERROR: no localconfig.vdf found under ~/.local/share/Steam/userdata/*/config/")

    for f in files:
        try:
            text = open(f, encoding="utf-8", errors="replace").read()
        except OSError as e:
            print("SKIP %s (%s)" % (f, e))
            continue
        new, old = patch(text, APPID, value)
        if old is None:
            print("SKIP %s — no block for AppId %s (game never launched from this account?)"
                  % (f, APPID))
            continue
        print("\nFILE %s" % f)
        print("  OLD LaunchOptions: %s" % (old or "(empty)"))
        print("  NEW LaunchOptions: %s" % (value or "(removed)"))
        if new == text:
            print("  -> already correct, nothing to do")
            continue
        if not a.apply:
            print("  -> DRY RUN (pass --apply to write)")
            continue
        bak = "%s.bak-%s" % (f, time.strftime("%Y%m%d-%H%M%S"))
        shutil.copy2(f, bak)
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(new)
        print("  -> WRITTEN (backup: %s)" % bak)

    if a.apply and not a.clear:
        print("\nDone. Start Steam and launch Easy Red 2 normally — it will come up headless "
              "inside the harness with DLC entitlements visible.\nControl socket: "
              "/tmp/ER2Harness.sock")


if __name__ == "__main__":
    main()
