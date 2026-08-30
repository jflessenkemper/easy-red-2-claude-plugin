#!/usr/bin/env python3
"""Easy Red 2 — Claude plugin MCP server (stdio JSON-RPC).

Exposes the ER2 gamescope-harness (see llm-wiki: live-game-harness-architecture.md) plus
ER2-specific modding tools as first-class Claude tools, so Claude can SEE the game, DRIVE it,
read the Lua decision trace, and hot-deploy brain scripts — all headless, without touching the
host cursor.

Tools
  er2_launch      start the harness + game headless (idempotent)
  er2_stop        stop the harness/game
  er2_state       harness STATE (ready / inner_alive) — gate every action on this
  er2_screenshot  current frame, returned INLINE as an image
  er2_click       click at x,y (optional reliable double-tap recipe)
  er2_key         key tap by name ("space","f3","p","escape","enter") or Win32 VK int
  er2_type        type a string (for the in-game F3 Lua console)
  er2_lua         run a Lua snippet via the F3 console (open, type, enter, close)
  er2_log         tail Player.log filtered by tag ([REALISTIC]/[EVENTS]/[BENCH]/errors)
  er2_deploy      luajit-validate + copy mod scripts into a mission's scripts/ tree
  er2_missions    list mission-editor missions and their deployed scripts

No third-party deps: hand-rolled JSON-RPC over stdio, raw AF_UNIX socket, `magick` (optional)
for downscaling screenshots.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "easy-red-2", "version": "1.0.0"}

# ---------------------------------------------------------------- configuration
# Everything is overridable by env (see .mcp.json), but defaults are DISCOVERED rather than
# hardcoded so the plugin works on any machine out of the box.
HOME = os.path.expanduser("~")


def _first_existing(paths, default=None):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return default


def _find_game_dir():
    cands = []
    # Steam library roots: default + any extra libraries declared in libraryfolders.vdf
    roots = [
        os.path.join(HOME, ".local/share/Steam/steamapps"),
        os.path.join(HOME, ".steam/steam/steamapps"),
        os.path.join(HOME, ".var/app/com.valvesoftware.Steam/.local/share/Steam/steamapps"),
    ]
    for r in list(roots):
        vdf = os.path.join(r, "libraryfolders.vdf")
        try:
            for line in open(vdf, encoding="utf-8", errors="replace"):
                line = line.strip()
                if '"path"' in line:
                    parts = line.split('"')
                    if len(parts) >= 4:
                        roots.append(os.path.join(parts[3], "steamapps"))
        except OSError:
            pass
    for r in roots:
        cands.append(os.path.join(r, "common", "Easy Red 2"))
    return _first_existing(cands, cands[0] if cands else "")


def _find_harness():
    cands = [
        os.path.join(HOME, "AOE-3-DE-Harness/build-f44/src/AOE3DEHarness"),
        os.path.join(HOME, "AOE-3-DE-Harness/AOE3DEHarness-x86_64.AppImage"),
        shutil.which("AOE3DEHarness") or "",
        shutil.which("gamescope") or "",  # last resort: stock gamescope (no control socket)
    ]
    return _first_existing(cands, "")


# Socket in $HOME, NOT /tmp: Steam launches the harness in a different mount namespace from
# sandboxed tooling with a private /tmp. The socket binds (ss -lx shows LISTEN) but is invisible
# to the client, which is indistinguishable from "harness not running". $HOME is always shared.
SOCK = os.environ.get("ER2_HARNESS_SOCK") or os.path.join(HOME, ".er2harness.sock")
HARNESS = os.environ.get("ER2_HARNESS_BIN") or _find_harness()
GAME_DIR = os.environ.get("ER2_GAME_DIR") or _find_game_dir()
GAME_BIN = os.path.join(GAME_DIR, "Easy Red 2.x86_64")
APPID = os.environ.get("ER2_APPID", "1324780")
CFG = os.environ.get("ER2_CFG_DIR") or _first_existing([
    os.path.join(HOME, ".config/unity3d/Corvostudio/Easy Red 2"),
    os.path.join(HOME, ".var/app/com.valvesoftware.Steam/.config/unity3d/Corvostudio/Easy Red 2"),
], os.path.join(HOME, ".config/unity3d/Corvostudio/Easy Red 2"))
PLAYER_LOG = os.path.join(CFG, "Player.log")
MISSION_DIR = os.path.join(CFG, "mission_editor")
MOD_SRC = os.environ.get("ER2_MOD_SRC") or os.path.join(HOME, "er2-realistic")
TMP = os.environ.get("ER2_TMP", "/tmp/er2_mcp")
# repo root, so error text can point at tools/ scripts by real path rather than a guess.
# server.py lives at <root>/plugins/easy-red-2/tools/er2_mcp/server.py
PLUGIN_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                           "..", "..", "..", ".."))
os.makedirs(TMP, exist_ok=True)

# Win32 VK codes — the harness maps VK -> evdev (src/harness/harness_input.cpp).
VK = {
    "space": 0x20, "enter": 0x0D, "return": 0x0D, "escape": 0x1B, "esc": 0x1B,
    "tab": 0x09, "backspace": 0x08, "delete": 0x2E,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "p": 0x50, "w": 0x57, "a": 0x41, "s": 0x53, "d": 0x44, "m": 0x4D,
    "y": 0x59, "n": 0x4E, "t": 0x54, "e": 0x45, "r": 0x52,
}


# ---------------------------------------------------------------- harness socket
class HarnessError(RuntimeError):
    pass


def hsend(cmds, timeout=10.0):
    """Send newline-delimited commands; return one reply line per command."""
    if not os.path.exists(SOCK):
        raise HarnessError(
            "harness socket not found at %s — call er2_launch first" % SOCK
        )
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(SOCK)
    except OSError as e:
        # A socket FILE can outlive the harness process; connecting then fails with
        # ECONNREFUSED. Treat it the same as "not running" and point at the fix.
        raise HarnessError(
            "harness not running (stale socket at %s: %s) — call er2_launch" % (SOCK, e)
        )
    out = []
    f = s.makefile("rwb")
    try:
        for c in cmds:
            f.write((c + "\n").encode())
            f.flush()
            line = f.readline()
            out.append(line.decode(errors="replace").strip() if line else "<no reply>")
    finally:
        try:
            s.close()
        except Exception:
            pass
    return out


def parse_state(line):
    """'OK pid=1 ready=1 ...' -> dict"""
    d = {}
    for tok in line.split():
        if "=" in tok:
            k, _, v = tok.partition("=")
            d[k] = v
    return d


def require_live():
    """Gate actions on the game actually being alive (wiki gotcha: a good screenshot is
    NOT proof the game is live — check inner_alive)."""
    st = parse_state(hsend(["STATE"])[0])
    if st.get("inner_alive") != "1":
        raise HarnessError(
            "game is not alive (inner_alive=%s, ready=%s) — relaunch with er2_launch"
            % (st.get("inner_alive"), st.get("ready"))
        )
    return st


# ---------------------------------------------------------------- images
def img_content(path, scale_to=1100, fmt="png"):
    """Read a PNG, optionally downscale with `magick`, return an MCP image content block."""
    src = path
    if scale_to and shutil.which("magick"):
        small = os.path.join(TMP, "shot_small.%s" % ("jpg" if fmt == "jpg" else "png"))
        try:
            subprocess.run(
                ["magick", path, "-resize", "%dx" % scale_to, small],
                check=True, capture_output=True, timeout=30,
            )
            src = small
        except Exception:
            src = path
    raw = Path(src).read_bytes()
    mime = "image/jpeg" if src.endswith((".jpg", ".jpeg")) else "image/png"
    return {
        "type": "image",
        "data": base64.b64encode(raw).decode("ascii"),
        "mimeType": mime,
    }


def text(s):
    return {"type": "text", "text": s}


# ---------------------------------------------------------------- tools
def _steam_launch_options():
    """Return (found, value) for Easy Red 2's Steam LaunchOptions.

    found=False means no localconfig.vdf or no entry for the app at all.
    The value is what Steam will prepend to the game command; the harness only gets injected
    when it wraps %command% in there.
    """
    import glob as _glob
    pats = [os.path.expanduser("~/.local/share/Steam/userdata/*/config/localconfig.vdf"),
            os.path.expanduser("~/.steam/steam/userdata/*/config/localconfig.vdf")]
    for pat in pats:
        for path in _glob.glob(pat):
            try:
                txt = open(path, "r", errors="replace").read()
            except OSError:
                continue
            # The app id appears MANY times in this file, and most are not the Apps entry: it also
            # shows up inside base64/hex token blobs on lines like `"1324780"  "3e0000...."`. Taking
            # the FIRST raw occurrence found one of those blobs, saw no LaunchOptions within it, and
            # reported the options as empty - so the preflight told the user to run a repair they
            # had just successfully run. The real entry is a KEY: the id alone on its line, with the
            # block following it. Match that shape, and only fall back to a loose scan if it is
            # absent, so a genuinely empty entry is still reported as empty.
            starts = [m.start() for m in
                      re.finditer(r'^[ \t]*"%s"[ \t]*$' % APPID, txt, re.M)]
            if not starts:
                starts = [m.start() for m in re.finditer(r'"%s"' % APPID, txt)]
            if not starts:
                continue
            for i in starts:
                m = re.search(r'"LaunchOptions"\s*"([^"]*)"', txt[i:i + 4000])
                if m:
                    return True, m.group(1)
            return True, ""
    return False, ""


def _workshop_gaps():
    """Workshop items Steam thinks are installed but whose content directory is missing.

    Why this matters: the editor hub enumerates installed Workshop items and reads each one's
    directory. A missing directory throws DirectoryNotFoundException INSIDE the enumeration, which
    kills the loading coroutine - the hub then sits on "LOADING Workshop campaigns" forever and the
    mission list never appears. There is no error dialog and the game stays responsive, so it reads
    as "slow" rather than "broken"; it cost a full debugging detour here.

    Note the enumeration ABORTS at the first bad item, so the log names only ONE id even when
    several are missing - do not treat the log as the complete list. This returns all of them.

    Common causes: an interrupted Steam download, a manually renamed/moved item (the classic being
    <id>.disabled, used to sideline a broken mod), or content deleted while still subscribed.
    Returns a list of missing ids (possibly empty).
    """
    acf = os.path.join(HOME, ".local/share/Steam/steamapps/workshop",
                       "appworkshop_%s.acf" % APPID)
    content = os.path.join(HOME, ".local/share/Steam/steamapps/workshop/content", APPID)
    try:
        txt = open(acf, "r", errors="replace").read()
    except OSError:
        return []
    i = txt.find('"WorkshopItemsInstalled"')
    if i < 0:
        return []
    # Stop at the sibling section so we do not also match ids from WorkshopItemDetails.
    j = txt.find('"WorkshopItemDetails"', i)
    installed = re.findall(r'^\s*"(\d{6,})"\s*$', txt[i:j if j > 0 else len(txt)], re.M)
    return [w for w in installed if not os.path.isdir(os.path.join(content, w))]


def _preflight_workshop():
    """Warning text for missing Workshop content, or None. Never blocks a launch: the game boots
    fine and only the EDITOR HUB hangs, so this must not stop someone doing non-editor work."""
    gaps = _workshop_gaps()
    if not gaps:
        return None
    content = os.path.join(HOME, ".local/share/Steam/steamapps/workshop/content", APPID)
    lines = ["WARNING: %d subscribed Workshop item(s) have no content directory:" % len(gaps)]
    for w in gaps[:8]:
        alt = os.path.join(content, w + ".disabled")
        lines.append("  %s%s" % (w, "   (found %s.disabled - just rename it back)" % w
                                 if os.path.isdir(alt) else ""))
    if len(gaps) > 8:
        lines.append("  ... and %d more" % (len(gaps) - 8))
    lines.append("The Mission Editor hub will HANG on 'LOADING Workshop campaigns' and the mission "
                 "list will never appear, so er2_play_mission/er2_missions cannot work.")
    lines.append("FIX: restore the directories (rename any *.disabled back), or unsubscribe the "
                 "items in Steam so the game stops enumerating them.")
    return "\n".join(lines)


def _with_workshop_warning(msg):
    """Append the Workshop-integrity warning to a launch result, if there is one."""
    warn = _preflight_workshop()
    return msg + "\n\n" + warn if warn else msg


def _preflight_steam(args):
    """Fail FAST when Steam mode is impossible, instead of timing out for minutes.

    Steam mode works ONLY if the harness already wraps %command% in the game's Steam Launch
    Options - that is the sole mechanism that gets the game running inside the harness while
    still receiving a Steam app ticket (which is what makes owned DLC visible). With the
    options cleared, Steam launches the game bare: no socket ever appears and er2_launch used
    to sit there for the full timeout and then say "launch timed out after waiting", which
    names neither the cause nor the fix.
    Returns an error string, or None if Steam mode looks viable.
    """
    found, opts = _steam_launch_options()
    if not found:
        return ("no Steam LaunchOptions entry found for app %s. Steam mode cannot inject the "
                "harness." % APPID)
    if "%command%" not in opts or "arness" not in opts:
        return ("Steam LaunchOptions for app %s do not wrap the harness around %%command%% "
                "(currently: %r).\n"
                "Steam mode CANNOT work without it - Steam would launch the game bare and no "
                "harness socket would ever appear.\n"
                "FIX:  close Steam, then run\n"
                "        python3 %s/tools/fix_steam_launch_options.py --apply\n"
                "      (dry-runs by default, backs up localconfig.vdf, and refuses to run while "
                "Steam is open because Steam overwrites the file on exit)\n"
                "ALTERNATIVE: er2_launch {\"via_steam\": false} works with no launch options at "
                "all - the plugin runs the harness itself - BUT the game then gets no DLC "
                "entitlement, so DLC maps show a dead \"Needs DLCs: <name>\" row and will not "
                "open." % (APPID, opts, PLUGIN_ROOT))
    return None


def t_launch(args):
    width = int(args.get("width", 1920))
    height = int(args.get("height", 1080))
    fps = int(args.get("fps", 30))
    if os.path.exists(SOCK):
        try:
            st = parse_state(hsend(["STATE"])[0])
            if st.get("inner_alive") == "1":
                return [text("already running: %s" % json.dumps(st))]
        except HarnessError:
            pass  # stale socket, fall through and relaunch

    # STEAM MODE (required for DLC): a directly-launched process cannot verify DLC
    # entitlements, so DLC missions show "Needs DLCs: ..." and refuse to open. Launching
    # through Steam's %command% wrapper (reaper SteamLaunch AppId=...) fixes it. Requires
    # launch options already set — see tools/fix_steam_launch_options.py.
    # NOTE: `steam -applaunch` silently does nothing; the steam:// URL is what works.
    # DEFAULTS ON. A directly-launched process cannot verify DLC entitlements, so every DLC map
    # silently becomes unselectable: the Mission Editor shows a dead "Needs DLCs: <name>" row that
    # highlights but never opens, with no error and no log line. Non-DLC maps still work, which
    # makes it look mission-specific when it is launch-mode specific. Costly to diagnose, free to
    # avoid - so the safe mode is the default and callers must opt OUT explicitly.
    if args.get("via_steam", True):
        problem = _preflight_steam(args)
        if problem:
            return [text("er2_launch PREFLIGHT FAILED (nothing was launched):\n\n" + problem)]
        try:
            os.path.exists(SOCK) and os.unlink(SOCK)
        except OSError:
            pass
        env = dict(os.environ)
        env.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")
        subprocess.Popen(["xdg-open", "steam://rungameid/%s" % APPID],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=env, start_new_session=True)
        deadline = time.time() + float(args.get("timeout_s", 180))
        while time.time() < deadline:
            if os.path.exists(SOCK):
                try:
                    st = parse_state(hsend(["STATE"])[0])
                    if st.get("ready") == "1" and st.get("inner_alive") == "1":
                        msg = ("launched via Steam (DLC entitlements available). STATE=%s"
                               % json.dumps(st))
                        return [text(_with_workshop_warning(msg))]
                except HarnessError:
                    pass
            time.sleep(3)
        return [text("Steam launch timed out. Check that launch options are set: "
                     "python3 tools/fix_steam_launch_options.py  (Steam must be shut down to "
                     "apply). Socket expected at %s" % SOCK)]
    if not os.path.exists(HARNESS):
        return [text("ERROR harness binary missing: %s" % HARNESS)]
    if not os.path.exists(GAME_BIN):
        return [text("ERROR game binary missing: %s" % GAME_BIN)]
    env = dict(os.environ)
    env.update({
        "XDG_RUNTIME_DIR": env.get("XDG_RUNTIME_DIR", "/run/user/1000"),
        "SteamAppId": APPID, "SteamGameId": APPID,
    })
    # Audio isolation (default ON): route the headless game to a null sink so it can NEVER
    # reach the speakers. Muting the sink-input by index is unreliable — FMOD recreates its
    # stream (and module-stream-restore can undo a mute), which leaks loud menu music over
    # whatever the user is actually playing. PULSE_SINK is honoured at stream-creation time.
    if args.get("mute", True):
        sink = os.environ.get("ER2_NULL_SINK", "er2_silence")
        try:
            have = subprocess.run(["pactl", "list", "short", "sinks"],
                                  capture_output=True, text=True, timeout=10).stdout
            if sink not in have:
                subprocess.run(
                    ["pactl", "load-module", "module-null-sink",
                     "sink_name=%s" % sink,
                     "sink_properties=device.description=EasyRed2-Silence"],
                    capture_output=True, text=True, timeout=10,
                )
            env["PULSE_SINK"] = sink
        except Exception:
            pass  # no pactl / no pipewire: fall through unmuted rather than fail the launch
    logf = open(os.path.join(TMP, "harness.log"), "wb")
    cmd = [
        HARNESS, "--keep-alive",
        "-W", str(width), "-H", str(height), "-w", str(width), "-h", str(height),
        "-r", str(fps), "--framerate-limit", str(fps),
        "--backend", "headless", "--xwayland-count", "1",
        "--harness-socket", SOCK,
        "--", GAME_BIN,
    ]
    p = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, env=env,
                         start_new_session=True)
    # wait for socket + ready
    deadline = time.time() + float(args.get("timeout_s", 90))
    last = "no socket yet"
    while time.time() < deadline:
        if os.path.exists(SOCK):
            try:
                st = parse_state(hsend(["STATE"])[0])
                last = json.dumps(st)
                if st.get("ready") == "1" and st.get("inner_alive") == "1":
                    msg = ("launched harness pid=%s; game ready. STATE=%s" % (p.pid, last)
                           + "\nNOTE: direct mode gets NO DLC entitlement - DLC maps show a dead "
                             "\"Needs DLCs: <name>\" sub-row in the mission list and will not open.")
                    return [text(_with_workshop_warning(msg))]
            except HarnessError as e:
                last = str(e)
        time.sleep(2)
    return [text("launch timed out after waiting. last=%s (see %s/harness.log)" % (last, TMP))]


def t_stop(args):
    killed = []
    try:
        st = parse_state(hsend(["STATE"])[0])
        for k in ("inner_pid", "pid"):
            pid = st.get(k)
            if pid and pid.isdigit():
                try:
                    os.kill(int(pid), 15)
                    killed.append("%s=%s" % (k, pid))
                except ProcessLookupError:
                    pass
    except HarnessError as e:
        return [text("nothing to stop (%s)" % e)]

    # WAIT for the harness socket to go away before returning. Returning the instant SIGTERM is
    # sent makes an immediately-following er2_launch fail with
    #   ConnectionResetError: [Errno 104] Connection reset by peer
    # because the socket is still being torn down. Reproduced three times in one session; every
    # occurrence cost a retry and ~30 s. The tool now owns the wait so callers do not have to
    # guess a sleep.
    deadline = time.time() + float(args.get("timeout_s", 30))
    while time.time() < deadline:
        if not os.path.exists(SOCK):
            break
        try:
            if parse_state(hsend(["STATE"])[0]).get("inner_alive") != "1":
                break
        except (HarnessError, OSError):
            break            # socket gone, refusing, or mid-teardown (BrokenPipe): done
        time.sleep(0.5)
    else:
        return [text("sent SIGTERM to %s, but the harness socket was still up after %ss - "
                     "wait before relaunching" % (", ".join(killed) or "nothing",
                                                  args.get("timeout_s", 30)))]
    time.sleep(1.0)          # brief settle; the unix socket unlink lags the process exit
    try:
        os.path.exists(SOCK) and os.unlink(SOCK)
    except OSError:
        pass
    return [text("sent SIGTERM to %s; harness down and socket clear - safe to relaunch"
                 % (", ".join(killed) or "nothing"))]


def t_state(args):
    return [text(hsend(["STATE"])[0])]


def t_screenshot(args):
    require_live()
    path = os.path.join(TMP, "shot.png")
    reply = hsend(["SCREENSHOT %s" % path])[0]
    if not reply.startswith("OK") or not os.path.exists(path):
        return [text("screenshot failed: %s" % reply)]
    scale = int(args.get("scale", 1100))
    out = []
    if args.get("note"):
        out.append(text(str(args["note"])))
    out.append(img_content(path, scale_to=scale))
    return out


def t_click(args):
    require_live()
    x, y = int(args["x"]), int(args["y"])
    button = int(args.get("button", 1))
    cmds = ["CLICK %d %d %d" % (x, y, button)]
    if args.get("reliable"):
        # wiki: scene-transition buttons often need two clicks ~0.6s apart
        hsend(cmds)
        time.sleep(0.6)
    return [text("; ".join(hsend(cmds)))]


def _vk_of(key):
    if isinstance(key, int):
        return key
    k = str(key).strip().lower()
    if k in VK:
        return VK[k]
    if k.startswith("0x"):
        return int(k, 16)
    if k.isdigit():
        return int(k)
    if len(k) == 1 and k.isalnum():
        return ord(k.upper())
    raise ValueError("unknown key %r (use a name like 'space'/'f3' or a VK int)" % key)


def t_key(args):
    require_live()
    vk = _vk_of(args["key"])
    return [text("KEY %s -> %s" % (hex(vk), hsend(["KEY %#04x" % vk])[0]))]


def t_type(args):
    """Type text. The harness has a native TYPE command — use it; falling back to
    per-character VK codes only if the build predates it."""
    require_live()
    s = str(args["text"])
    reply = hsend(["TYPE %s" % s])[0]
    if reply.startswith("OK"):
        return [text("typed %r via native TYPE" % s)]
    cmds = []
    for ch in s:
        try:
            cmds.append("KEY %#04x" % _vk_of(ch))
        except ValueError:
            continue
    if not cmds:
        return [text("TYPE unsupported (%s) and nothing VK-mappable in %r" % (reply, s))]
    hsend(cmds)
    return [text("TYPE unsupported (%s); sent %d VK keys instead" % (reply, len(cmds)))]


# ---- scripted UI navigation -------------------------------------------------
# Verified coordinates (see docs/ui-map.md). Encoded here so menu driving is a single
# deterministic call instead of hand-clicking, and so a UI change is fixed in one place.
UI = {
    "menu_mission_editor": (204, 820),
    "hub_mission_editor": (1392, 403),
    "list_row1_y": 79,          # first map row; pitch 52
    "list_row_pitch": 52,
    "list_x": 1544,
    "edit_mission": (960, 371),
    "sigma": (49, 1044),
    "save_icon": (380, 1044),
    "btn_save": (300, 108),
    "btn_play": (300, 183),
    "btn_play_from_phase": (300, 258),
    "modal_ok": (960, 618),
}


def _click(x, y, settle=1.0, reliable=True):
    hsend(["MOVE %d %d" % (x, y)])
    time.sleep(0.4)
    hsend(["CLICK %d %d 1" % (x, y)])
    if reliable:
        time.sleep(0.6)
        hsend(["CLICK %d %d 1" % (x, y)])
    time.sleep(settle)


def _log_lines():
    """Current Player.log length, or 0. Used as a before/after mark."""
    try:
        with open(PLAYER_LOG, "rb") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def _verify_playing(mark, settle_s=25.0):
    """Did the game actually leave the Mission Editor and load the mission?

    Proof: a real mission load re-loads the phase script, which logs 'initial brain sweep' once
    per load. Editor previews do NOT re-load it, so the marker cannot be faked by editor activity.
    Returns (ok, reason).
    """
    deadline = time.time() + settle_s
    while time.time() < deadline:
        try:
            with open(PLAYER_LOG, "rb") as fh:
                tail = fh.read().splitlines()[mark:]
        except OSError:
            return False, "no Player.log to check"
        if any(b"initial brain sweep" in ln for ln in tail):
            return True, ""
        time.sleep(2.0)
    try:
        with open(PLAYER_LOG, "rb") as fh:
            tail = fh.read().splitlines()[mark:]
    except OSError:
        return False, "no Player.log to check"
    if not any(b"[EVENTS]" in ln or b"[REALISTIC]" in ln for ln in tail):
        # "Silent" has TWO causes and they need opposite responses. The mod ships with
        # DEBUG = false, which gates every dbg()/logonly() line - so a correctly deployed
        # SHIPPING build is legitimately silent and this check can never pass. Saying
        # "is the mod deployed?" there sends you to re-deploy something that is already fine.
        quiet = _deployed_debug_off(args_mission=None)
        if quiet:
            return False, ("no mod output - but the deployed build has DEBUG = false, so it is "
                           "SILENT BY DESIGN and this check cannot confirm play either way. "
                           "This is not evidence of a problem. Screenshot to confirm, or deploy a "
                           "verification build with DEBUG = true if you need the log markers")
        return False, "no mod output at all since the Play click - is the mod deployed?"
    return False, ("mod is logging but the phase script never re-loaded, which is what an "
                   "editor preview looks like")


def _deployed_debug_off(args_mission=None):
    """True if a deployed phase script has DEBUG = false (so the mod logs nothing).

    Checks every mission's scripts/mission/phase_0.lua rather than guessing which one is loaded:
    if they all ship quiet, silence explains itself.
    """
    found_any, all_quiet = False, True
    try:
        names = os.listdir(MISSION_DIR)
    except OSError:
        return False
    for name in names:
        p = os.path.join(MISSION_DIR, name, "scripts", "mission", "phase_0.lua")
        if not os.path.isfile(p):
            continue
        try:
            head = open(p, "r", errors="replace").read(4000)
        except OSError:
            continue
        if not re.search(r'^local DEBUG\s*=', head, re.M):
            continue
        found_any = True
        if not re.search(r'^local DEBUG\s*=\s*false', head, re.M):
            all_quiet = False
    return found_any and all_quiet


def t_play_mission(args):
    """Drive: main menu -> Mission Editor -> pick map row -> pick its mission -> Edit
    mission -> (sigma) -> save panel -> Play. Coordinates are the verified ones above.

    Assumes the game is sitting on the MAIN MENU. Selecting a map expands a mission
    sub-row directly beneath it (row pitch 52), so the mission row is map_row_y + pitch.
    """
    require_live()
    row = int(args.get("map_row", 1))
    load_s = float(args.get("load_s", 75))
    steps = []
    log_mark = _log_lines()      # for the end-state check below

    _click(*UI["menu_mission_editor"], settle=5)
    steps.append("mission editor")
    _click(*UI["hub_mission_editor"], settle=6)
    steps.append("editor hub")

    map_y = UI["list_row1_y"] + (row - 1) * UI["list_row_pitch"]
    _click(UI["list_x"], map_y, settle=2, reliable=False)
    steps.append("selected map row %d (y=%d)" % (row, map_y))

    mission_y = map_y + UI["list_row_pitch"]
    _click(UI["list_x"], mission_y, settle=3, reliable=False)
    steps.append("selected mission sub-row (y=%d)" % mission_y)

    _click(*UI["edit_mission"], settle=3, reliable=False)
    steps.append("clicked Edit mission; waiting %ds for map load" % load_s)
    time.sleep(load_s)

    if args.get("play", True):
        _click(*UI["sigma"], settle=2, reliable=False)
        _click(*UI["save_icon"], settle=2, reliable=False)
        _click(*UI["btn_play"], settle=5, reliable=False)
        steps.append("clicked Play")

    path = os.path.join(TMP, "nav.png")
    hsend(["SCREENSHOT %s" % path])
    # VERIFY THE END STATE. This tool used to report "clicked Play" whether or not the game
    # actually left the Mission Editor, and a swallowed Play click looks identical to success:
    # phase scripts EXECUTE in the editor, so [REALISTIC]/[EVENTS] lines keep appearing and the
    # log looks healthy. A whole analysis pass was once run against a battle that never started.
    #
    # The check is log-based, so it needs no vision: a real mission load RE-LOADS the phase
    # script, which prints "initial brain sweep" exactly once per load. Seeing a NEW one after
    # the Play click is proof the mission actually loaded. (It requires the Realistic phase
    # script to be deployed; if it is not, we say so rather than claiming success.)
    verified, why = _verify_playing(log_mark)
    steps.append("VERIFIED playing" if verified else "NOT VERIFIED: " + why)

    body = "navigation steps:\n- " + "\n- ".join(steps)
    if not verified:
        body += ("\n\nWARNING: could not confirm the game left the Mission Editor (%s).\n"
                 "Do NOT treat log activity as proof of play - phase scripts run in the editor "
                 "too. Screenshot to check, and if it is still in the editor drive it manually: "
                 "Sigma (49,1044) -> Save/Play (380,1044) -> Play (300,184)." % why)
        # Two silent causes look identical from here, so name both rather than only the clicks:
        # a hung Workshop enumeration (mission list never renders), and a DLC-gated map (the
        # mission sub-row is replaced by a dead "Needs DLCs: <name>" label that cannot be clicked).
        warn = _preflight_workshop()
        if warn:
            body += "\n\n" + warn
        body += ("\n\nALSO CHECK, in the order these actually happen:"
                 "\n1. STILL ON THE SPLASH? This tool assumes the MAIN MENU. On the "
                 "\"Press Space or Start\" screen every click is swallowed and all steps above "
                 "report OK while nothing happened. Send er2_key {\"key\": \"space\"}, confirm the "
                 "main menu with a screenshot, then retry. A single space can be missed while the "
                 "game is still loading, so verify rather than assuming."
                 "\n2. DLC-GATED MAP? If the map needs a DLC and the game was launched with "
                 "er2_launch {\"via_steam\": false}, the mission sub-row reads "
                 "\"Needs DLCs: <name>\" and is inert. Relaunch via Steam.")
    out = [text(body)]
    if os.path.exists(path):
        out.append(img_content(path, scale_to=int(args.get("scale", 1000))))
    return out


def t_lua(args):
    """Open the F3 console, type a Lua snippet, submit, close. This is the LIVE TUNING
    channel: e.g. global.set(0.9,"realistic_aggression") with no mission restart."""
    require_live()
    code = str(args["code"])
    hsend(["KEY %#04x" % VK["f3"]])
    time.sleep(0.4)
    t_type({"text": code})
    time.sleep(0.2)
    hsend(["KEY %#04x" % VK["enter"]])
    time.sleep(0.3)
    if args.get("close", True):
        hsend(["KEY %#04x" % VK["f3"]])
    return [text("submitted to F3 console: %s" % code)]


def t_log(args):
    tag = args.get("tag", "")
    lines = int(args.get("lines", 60))
    if not os.path.exists(PLAYER_LOG):
        return [text("no Player.log at %s" % PLAYER_LOG)]
    pats = {
        "realistic": r"\[REALISTIC\]",
        "events": r"\[EVENTS\]",
        "bench": r"\[BENCH\]",
        "watch": r"\[WATCH\]",
        "errors": r"Lua error|guard\(once\)|not allowed as global|cannot access field|Exception",
        "": r"\[REALISTIC\]|\[EVENTS\]|\[BENCH\]|Lua error",
    }
    pat = pats.get(str(tag).lower(), str(tag))
    try:
        out = subprocess.run(
            ["grep", "-aE", pat, PLAYER_LOG],
            capture_output=True, text=True, timeout=60,
        ).stdout.splitlines()
    except Exception as e:
        return [text("grep failed: %s" % e)]
    total = len(out)
    tail = out[-lines:]
    if args.get("shapes"):
        import re as _re
        from collections import Counter
        norm = Counter(_re.sub(r"-?\d+(\.\d+)?", "N", l) for l in out)
        body = "\n".join("%6d  %s" % (c, s) for s, c in norm.most_common(25))
        return [text("%d matching lines; top shapes:\n%s" % (total, body))]
    return [text("%d matching lines (showing last %d):\n%s" % (total, len(tail), "\n".join(tail)))]


def _run_offline_tests():
    """Run the mod's offline harnesses, if it ships any, BEFORE deploying.

    Syntax validation was never enough: every silent bug this mod has shipped parsed perfectly.
    rosterIndex() compiled to a nil global and killed the brain; safe() was a nil global in the
    phase script; the phase loop deadlocked. None was a syntax error, and Easy Red 2 does not
    surface a coroutine death as a Lua error, so all of them reached a real battle and showed
    only silence there.

    The harnesses execute the scripts against a stubbed runtime and cost milliseconds. Deploying
    a build that fails them means knowingly starting a ~15-minute battle that cannot work.
    Returns an error string, or None.
    """
    lua = shutil.which("luajit")
    if not lua:
        return None                      # no luajit: syntax check already handled elsewhere
    failures = []
    for name in ("tests/offline_brain.lua", "tests/offline_phase.lua"):
        path = os.path.join(MOD_SRC, name)
        if not os.path.exists(path):
            continue                     # the mod does not ship this harness
        try:
            r = subprocess.run([lua, name], cwd=MOD_SRC, capture_output=True,
                               text=True, timeout=60)
        except Exception as e:
            failures.append("%s could not run: %s" % (name, e))
            continue
        if r.returncode != 0:
            # Show the FAILING lines, not the tail. The tail is mostly passes, so a naive
            # [-8:] hid the actual failure behind a wall of green - an error message that
            # does not show the error.
            all_lines = (r.stdout + r.stderr).strip().splitlines()
            bad_lines = [l for l in all_lines if "FAIL" in l or "ERROR" in l]
            summary = [l for l in all_lines if "PASS " in l and "FAIL" in l]
            shown = (bad_lines[:6] or all_lines[-4:]) + summary[-1:]
            seen, shown = set(), [l for l in shown if not (l in seen or seen.add(l))]
            failures.append("%s FAILED:\n    %s" % (name, "\n    ".join(shown)))
    if failures:
        return ("offline tests failed - NOT deploying, because a battle cannot verify what the "
                "desk already says is broken:\n\n" + "\n\n".join(failures))
    return None


def t_deploy(args):
    mission = str(args["mission"])
    mdir = os.path.join(MISSION_DIR, mission)
    if not os.path.isdir(mdir):
        avail = sorted(os.listdir(MISSION_DIR)) if os.path.isdir(MISSION_DIR) else []
        return [text("no such mission %r. available: %s" % (mission, avail))]
    # Gate on the mod's own offline tests before touching the mission. Skippable with
    # skip_tests=true for the rare case of deliberately deploying a known-broken build to
    # reproduce something.
    if not args.get("skip_tests"):
        problem = _run_offline_tests()
        if problem:
            return [text("er2_deploy REFUSED (nothing was copied):\n\n" + problem)]
    ai = os.path.join(mdir, "scripts", "AI")
    ms = os.path.join(mdir, "scripts", "mission")
    os.makedirs(ai, exist_ok=True)
    os.makedirs(ms, exist_ok=True)
    # (source, dest dir, dest name, required). A required source that is absent aborts the
    # deploy; an optional one is skipped, so bench/helper scripts may be deleted from the mod
    # without breaking deployment.
    # The phase script goes in as EVERY phase, not just phase_0.
    #
    # ER2 runs the script belonging to the CURRENT phase, so a mission that advances past phase 0
    # with only phase_0.lua present has no phase script at all from that point on. Each copy reads
    # MY_PHASE from er2.getCurrentPhaseId() at load, so it self-identifies and needs no per-phase
    # editing; copies for phases a mission does not have are inert, never loaded.
    #
    # HONESTY NOTE - this is NOT a fix for the phase-loop death, which was measured separately and
    # is NOT caused by a phase advance. Deploying all phases did not change it: the phase never
    # advanced in the test (one "initial brain sweep", obj1 still the only objective), yet the loop
    # still stopped. The loop dies at OBJECTIVE CAPTURE. See docs/ui-map.md for the evidence.
    plan = [
        ("Realistic.lua", ai, "Realistic.lua", True),
        ("WatchSquad.lua", ai, "WatchSquad.lua", False),
        ("bench_probe.lua", ai, "bench_probe.lua", False),
        ("bench_watch.lua", ms, "bench_watch.lua", False),
    ]
    phases = int(args.get("phases", 8))
    for n in range(phases):
        plan.append(("RealisticEvents.lua", ms, "phase_%d.lua" % n, n == 0))
    report = []
    luajit = shutil.which("luajit")
    for src_name, dst_dir, dst_name, required in plan:
        src = os.path.join(MOD_SRC, src_name)
        if not os.path.exists(src):
            if required:
                report.append("FAIL %s (required source not found in %s)" % (src_name, MOD_SRC))
                return [text("deploy to %s ABORTED:\n%s" % (mission, "\n".join(report)))]
            report.append("SKIP %s (absent)" % src_name)
            continue
        if luajit:
            r = subprocess.run(
                [luajit, "-e", "assert(loadfile('%s'))" % src],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                report.append("FAIL syntax %s: %s" % (src_name, (r.stderr or "").strip()[:200]))
                continue
        shutil.copy2(src, os.path.join(dst_dir, dst_name))
        report.append("OK %s -> %s" % (src_name, dst_name))
    return [text("deploy to %s:\n%s" % (mission, "\n".join(report)))]


def t_missions(args):
    if not os.path.isdir(MISSION_DIR):
        return [text("no mission_editor dir at %s" % MISSION_DIR)]
    out = []
    for m in sorted(os.listdir(MISSION_DIR)):
        p = os.path.join(MISSION_DIR, m)
        if not os.path.isdir(p):
            continue
        luas = []
        for root, _d, files in os.walk(os.path.join(p, "scripts")):
            for f in files:
                if f.endswith(".lua"):
                    luas.append(os.path.relpath(os.path.join(root, f), p))
        out.append("%s\n    %s" % (m, ", ".join(sorted(luas)) if luas else "(no scripts)"))
    return [text("\n".join(out))]


TOOLS = {
    "er2_launch": {
        "fn": t_launch,
        "description": "Launch Easy Red 2 HEADLESS inside the gamescope harness (no host window, "
                       "does not touch the host cursor). Idempotent: returns early if already alive. "
                       "Waits until the game reports ready. "
                       "USE via_steam=true WHENEVER DLC CONTENT IS NEEDED: a directly-launched "
                       "process cannot verify DLC entitlements, so DLC missions show "
                       "'Needs DLCs: ...' and will not open. via_steam launches through Steam's "
                       "%command% wrapper instead (requires launch options set once via "
                       "tools/fix_steam_launch_options.py).",
        "schema": {"type": "object", "properties": {
            "width": {"type": "integer", "description": "output width (default 1920)"},
            "height": {"type": "integer", "description": "output height (default 1080)"},
            "fps": {"type": "integer", "description": "framerate cap (default 30)"},
            "mute": {"type": "boolean", "description": "route game audio to a null sink so it "
                     "cannot reach the speakers (default TRUE — leave on unless you need sound)"},
            "via_steam": {"type": "boolean", "description": "launch through Steam so DLC "
                          "entitlements are visible (REQUIRED for DLC maps/missions)"},
            "timeout_s": {"type": "integer", "description": "seconds to wait for ready (default 90)"}}},
    },
    "er2_stop": {
        "fn": t_stop,
        "description": "Stop the headless game and harness (SIGTERM to inner game then compositor).",
        "schema": {"type": "object", "properties": {}},
    },
    "er2_state": {
        "fn": t_state,
        "description": "Harness STATE: pid, uptime_ms, internal_w/h, ready (first frame committed), "
                       "inner_pid, inner_alive. ALWAYS gate actions on inner_alive=1 — a good "
                       "screenshot alone is NOT proof the game is live.",
        "schema": {"type": "object", "properties": {}},
    },
    "er2_screenshot": {
        "fn": t_screenshot,
        "description": "Capture the current game frame, returned INLINE as an image. Use this to see "
                       "menus, the mission editor, and actual soldier behaviour in-world.",
        "schema": {"type": "object", "properties": {
            "scale": {"type": "integer", "description": "downscale width px (default 1100; 0 = full res)"},
            "note": {"type": "string", "description": "optional caption echoed before the image"}}},
    },
    "er2_click": {
        "fn": t_click,
        "description": "Click at screen coordinates (1:1 with screenshot pixels at 1920x1080). "
                       "Set reliable=true for scene-transition buttons that need a double tap ~0.6s apart.",
        "schema": {"type": "object", "properties": {
            "x": {"type": "integer"}, "y": {"type": "integer"},
            "button": {"type": "integer", "description": "1=left (default), 3=right"},
            "reliable": {"type": "boolean", "description": "double-tap recipe for menu buttons"}},
            "required": ["x", "y"]},
    },
    "er2_key": {
        "fn": t_key,
        "description": "Tap a key. Accepts a friendly name ('space','escape','f3','p','enter','w') "
                       "or a Win32 VK code int. 'p' copies a world position as vec3 in the editor; "
                       "'f3' toggles the in-game Lua console.",
        "schema": {"type": "object", "properties": {
            "key": {"type": ["string", "integer"]}}, "required": ["key"]},
    },
    "er2_type": {
        "fn": t_type,
        "description": "Type a literal string into the focused field (US-ANSI mapping; unmappable "
                       "characters are skipped).",
        "schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    },
    "er2_lua": {
        "fn": t_lua,
        "description": "Run a Lua snippet in the in-game F3 console (opens F3, types, submits, closes). "
                       "This is the LIVE TUNING channel — e.g. global.set(0.9,\"realistic_aggression\") "
                       "retunes the soldier brain mid-battle with no mission restart.",
        "schema": {"type": "object", "properties": {
            "code": {"type": "string", "description": "Lua to execute, e.g. print(er2.getMapName())"},
            "close": {"type": "boolean", "description": "close the console afterwards (default true)"}},
            "required": ["code"]},
    },
    "er2_play_mission": {
        "fn": t_play_mission,
        "description": "Drive the menus and START a custom mission, in one call: Mission Editor "
                       "-> pick the map row -> pick its mission sub-row -> Edit mission -> save "
                       "panel -> Play. Uses the verified coordinates in docs/ui-map.md, so no "
                       "hand-clicking. Game must be on the MAIN MENU. Returns a screenshot of "
                       "where it ended up. NOTE: custom missions cannot be started from Campaigns "
                       "or Multiplayer — only from inside the editor's save panel.",
        "schema": {"type": "object", "properties": {
            "map_row": {"type": "integer", "description": "1-based row of the MAP in the Local "
                        "list (rows are maps; the mission appears as a sub-row beneath)"},
            "play": {"type": "boolean", "description": "click Play at the end (default true); "
                     "false stops in the editor"},
            "load_s": {"type": "number", "description": "seconds to wait for the map to load "
                       "(default 75)"},
            "scale": {"type": "integer", "description": "screenshot downscale width"}}},
    },
    "er2_log": {
        "fn": t_log,
        "description": "Read the ER2 Player.log filtered to the mod's telemetry. tag: 'realistic' "
                       "(per-soldier decisions), 'events' (kill feed/objectives), 'bench' (API probe), "
                       "'watch', 'errors' (Lua errors/guards), or a custom regex. shapes=true "
                       "aggregates by message shape (best first look at a 50MB log).",
        "schema": {"type": "object", "properties": {
            "tag": {"type": "string"}, "lines": {"type": "integer"},
            "shapes": {"type": "boolean"}}},
    },
    "er2_deploy": {
        "fn": t_deploy,
        "description": "luajit-validate the mod's Lua then copy it into a mission: brain scripts to "
                       "scripts/AI/, RealisticEvents.lua to scripts/mission/phase_0.lua AND every "
                       "other phase_<n>.lua. Installing it for every phase is REQUIRED, not "
                       "belt-and-braces: the engine tears the phase script's coroutine down when "
                       "the mission advances a phase, so a phase-0-only deploy leaves objective "
                       "attraction, the bail-out drain and the fire-mission consumer silently dead "
                       "from the first objective capture onward. Refuses to deploy a file that "
                       "fails syntax check.",
        "schema": {"type": "object", "properties": {
            "skip_tests": {"type": "boolean", "description": "deploy even if the mod's offline tests fail (default false)"},
            "phases": {"type": "integer", "description": "how many phase_<n>.lua copies to install (default 8). Extra copies for phases the mission does not have are never loaded."},
                "mission": {"type": "string", "description": "mission-editor folder name, e.g. ME_Stonne_38n85202"}},
            "required": ["mission"]},
    },
    "er2_missions": {
        "fn": t_missions,
        "description": "List mission-editor missions and which mod scripts are currently deployed in each.",
        "schema": {"type": "object", "properties": {}},
    },
}


def _tools_list():
    return [{"name": n, "description": t["description"], "inputSchema": t["schema"]}
            for n, t in TOOLS.items()]


def handle(msg):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO}}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": _tools_list()}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = TOOLS.get(name)
        if not tool:
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [text("unknown tool %s" % name)], "isError": True}}
        try:
            content = tool["fn"](args)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": content, "isError": False}}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": mid, "result": {
                "content": [text("ERROR in %s: %s: %s" % (name, type(e).__name__, e))],
                "isError": True}}
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "method not found: %s" % method}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        try:
            resp = handle(msg)
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32603, "message": "internal error: %s" % e}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
