#!/usr/bin/env python3
"""Virtual Xbox-style gamepad over /dev/uinput, for driving ER2's Free Camera.

Why this exists
---------------
ER2's Free Camera cannot be aimed through the compositor. Absolute warps, true
relative motion (wlr_relative_pointer_manager_v1), relative motion with each mouse
button held, and gamescope's --force-grab-cursor were all measured as having NO
effect on camera orientation (2026-09-12; judged by sky-fraction and landmark-x,
not by frame hashes, which differ even when the camera has not moved).

But the game's own metadata names `RightStickX`, `RightStickY`, `rotationInput`
and `analogSensibilityMultiplierFreeCamera` -- the Free Camera reads the RIGHT
ANALOG STICK for rotation. A uinput device is created at the kernel evdev layer,
which SDL/Proton reads directly from /dev/input/event*, BELOW the compositor. So
gamepad input bypasses the entire Wayland path that swallows mouse motion.

Safety
------
Creating a virtual gamepad is globally visible: any running game may switch to
controller prompts or change its input handling. This tool therefore REFUSES to
create a device while a Steam game other than Easy Red 2 is running, unless
--force is given. The user has twice asked not to have their games disturbed.
"""

import argparse
import ctypes
import fcntl
import os
import struct
import sys
import time

UINPUT = "/dev/uinput"

# Easy Red 2. Any other AppId running means someone else is playing.
ER2_APPID = "1324780"

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0
ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = 0, 1, 2, 3, 4, 5
ABS_HAT0X, ABS_HAT0Y = 16, 17

# A minimal face/shoulder set. SDL needs buttons present to classify the device
# as a gamepad rather than a bare joystick.
BUTTONS = [0x130, 0x131, 0x133, 0x134, 0x136, 0x137, 0x13A, 0x13B, 0x13C, 0x13D, 0x13E]

UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045567

# Stick range. Matches a real Xbox pad closely enough for SDL's mappings.
AXIS_MIN, AXIS_MAX = -32768, 32767

ABS_AXES = [ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ, ABS_HAT0X, ABS_HAT0Y]


def foreign_steam_games():
    """AppIds of running Steam games that are NOT Easy Red 2.

    Scans /proc rather than using pgrep -f, which is blocked in this environment
    because it matches the calling shell.
    """
    # Test seam: ER2_FAKE_APPIDS lets the gate prove this guard actually blocks,
    # without needing a real game running. Comma-separated, empty string = none.
    fake = os.environ.get("ER2_FAKE_APPIDS")
    if fake is not None:
        return sorted(a for a in fake.split(",") if a and a != ER2_APPID)

    found = set()
    mypid = str(os.getpid())
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or entry == mypid:
            continue
        try:
            with open("/proc/%s/cmdline" % entry, "rb") as fh:
                cmd = fh.read().replace(b"\0", b" ").decode("utf-8", "replace")
        except (IOError, OSError):
            continue
        marker = "SteamLaunch AppId="
        idx = cmd.find(marker)
        if idx == -1:
            continue
        appid = ""
        for ch in cmd[idx + len(marker):]:
            if ch.isdigit():
                appid += ch
            else:
                break
        if appid and appid != ER2_APPID:
            found.add(appid)
    return sorted(found)


class VirtualPad(object):
    """An Xbox-360-alike pad. Use as a context manager so it is always destroyed."""

    def __init__(self, name="ER2 Virtual Pad"):
        self.name = name
        self.fd = None

    def __enter__(self):
        self.fd = os.open(UINPUT, os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_ABS)
        fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_SYN)
        for btn in BUTTONS:
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, btn)
        for axis in ABS_AXES:
            fcntl.ioctl(self.fd, UI_SET_ABSBIT, axis)

        # struct uinput_user_dev: name[80], input_id{bus,vendor,product,version},
        # ff_effects_max, then absmax/absmin/absfuzz/absflat, 64 int32 each.
        absmax = [0] * 64
        absmin = [0] * 64
        absfuzz = [0] * 64
        absflat = [0] * 64
        for axis in (ABS_X, ABS_Y, ABS_RX, ABS_RY):
            absmax[axis] = AXIS_MAX
            absmin[axis] = AXIS_MIN
            absflat[axis] = 16          # small deadzone, as a real pad reports
        for axis in (ABS_Z, ABS_RZ):    # triggers
            absmax[axis] = 255
        for axis in (ABS_HAT0X, ABS_HAT0Y):
            absmax[axis] = 1
            absmin[axis] = -1

        # Identify as a Microsoft X-Box 360 pad so SDL applies a known mapping.
        payload = self.name.encode()[:79].ljust(80, b"\0")
        payload += struct.pack("HHHH", 0x03, 0x045E, 0x028E, 0x0110)
        payload += struct.pack("I", 0)
        for table in (absmax, absmin, absfuzz, absflat):
            payload += struct.pack("64i", *table)
        os.write(self.fd, payload)
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.4)   # let udev/SDL notice the new device
        return self

    def __exit__(self, *_exc):
        if self.fd is not None:
            try:
                fcntl.ioctl(self.fd, UI_DEV_DESTROY)
            except OSError:
                pass
            os.close(self.fd)
            self.fd = None

    def _emit(self, etype, code, value):
        # struct input_event on 64-bit: timeval(2x long) + u16 + u16 + s32
        os.write(self.fd, struct.pack("llHHi", 0, 0, etype, code, value))

    def _sync(self):
        self._emit(EV_SYN, SYN_REPORT, 0)

    def stick(self, rx, ry):
        """Hold the right stick at (rx, ry), each in [-1.0, 1.0]."""
        self._emit(EV_ABS, ABS_RX, int(max(-1.0, min(1.0, rx)) * AXIS_MAX))
        self._emit(EV_ABS, ABS_RY, int(max(-1.0, min(1.0, ry)) * AXIS_MAX))
        self._sync()

    def centre(self):
        for axis in (ABS_X, ABS_Y, ABS_RX, ABS_RY):
            self._emit(EV_ABS, axis, 0)
        self._sync()

    def look(self, rx, ry, seconds, hz=60):
        """Hold the right stick deflected for `seconds`, then re-centre.

        Analog look is a RATE, not a displacement: the camera turns for as long
        as the stick is held. Duration is the control, unlike mouse deltas.
        """
        self.centre()
        deadline = time.time() + seconds
        period = 1.0 / hz
        while time.time() < deadline:
            self.stick(rx, ry)
            time.sleep(period)
        self.centre()
        time.sleep(0.1)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rx", type=float, default=0.0, help="right stick X, -1..1 (yaw)")
    ap.add_argument("--ry", type=float, default=0.0, help="right stick Y, -1..1 (pitch)")
    ap.add_argument("--seconds", type=float, default=1.0, help="how long to hold")
    ap.add_argument("--hold-open", type=float, default=0.0,
                    help="keep the device alive this long after the sweep, so a "
                         "separate screenshot call still sees the same pad")
    ap.add_argument("--daemon", metavar="FIFO",
                    help="create the pad, then read '<rx> <ry> <seconds>' command "
                         "lines from FIFO until told 'quit'. The pad must exist "
                         "BEFORE the game starts: Proton's pressure-vessel container "
                         "bind-mounts /dev/input at startup and SDL enumerates pads at "
                         "init, so a device created later is invisible to the game.")
    ap.add_argument("--probe", action="store_true",
                    help="create and destroy the device, reporting only whether "
                         "uinput works -- makes no input")
    ap.add_argument("--force", action="store_true",
                    help="create the pad even if another Steam game is running")
    args = ap.parse_args(argv)

    if not os.access(UINPUT, os.W_OK):
        print("FAIL %s is not writable by this user" % UINPUT, file=sys.stderr)
        return 2

    foreign = foreign_steam_games()
    if foreign and not args.force:
        print("REFUSING: Steam game(s) running with AppId %s." % ", ".join(foreign),
              file=sys.stderr)
        print("A new virtual gamepad is globally visible and can change that "
              "game's input handling. Wait, or pass --force if the user agreed.",
              file=sys.stderr)
        return 3

    with VirtualPad() as pad:
        if args.probe:
            print("OK virtual gamepad created and destroyed cleanly")
            return 0

        if args.daemon:
            if not os.path.exists(args.daemon):
                os.mkfifo(args.daemon)
            print("OK pad live, reading commands from %s" % args.daemon, flush=True)
            while True:
                # Reopening per message: a FIFO read returns EOF each time the
                # last writer closes, so this loop simply waits for the next one.
                with open(args.daemon) as fifo:
                    for line in fifo:
                        line = line.strip()
                        if not line:
                            continue
                        if line == "quit":
                            print("OK pad destroyed", flush=True)
                            return 0
                        try:
                            rx, ry, secs = (float(v) for v in line.split())
                        except ValueError:
                            print("ERR bad command %r" % line, flush=True)
                            continue
                        pad.look(rx, ry, secs)
                        print("OK %s" % line, flush=True)
        pad.look(args.rx, args.ry, args.seconds)
        if args.hold_open > 0:
            time.sleep(args.hold_open)
        print("OK held right stick rx=%.2f ry=%.2f for %.2fs"
              % (args.rx, args.ry, args.seconds))
    return 0


if __name__ == "__main__":
    sys.exit(main())
