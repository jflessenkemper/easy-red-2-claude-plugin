---
name: visual-test
description: Visually PROVE an Easy Red 2 mod behaviour on screen — deploy, launch, get in-mission, enter Free Camera, ascend, orbit for a 360° panorama, and reject empty frames automatically so a screenshot actually counts as evidence.
allowed-tools: er2_deploy, er2_launch, er2_state, er2_play_mission, er2_screenshot, er2_click, er2_key, er2_look, er2_move_rel, er2_button, er2_log, Bash, Read
---

Visually verify: "$ARGUMENTS" (if empty, ask what behaviour is supposed to be visible, and in
which mission — "take a screenshot" is not a testable claim).

## The one fact that makes this work

**ER2's Free Camera cannot be aimed by this harness. Measured, not assumed — 2026-09-12.**

Do not spend runs trying. The full result:

| Input | Path | Result |
|---|---|---|
| Absolute warp (`MOVE`/`DRAG`, `er2_click`) | `wlserver_mousewarp` | camera never moves |
| Relative motion (`LOOK`/`MOVE_REL`) | `wlserver_mousemotion` → relative-pointer-v1 | camera never moves |
| Relative + button held (1, 2 and 3) | as above | camera never moves |
| Relative + `--force-grab-cursor` | forces relative mouse mode | camera never moves |
| `W` translation (90 taps) | key events | landmarks at **identical** x — no movement |
| `E` / `Q` altitude | key events | **WORKS** — the only camera control that responds |

How each was judged, because "the frame changed" is NOT evidence — the scene is live, so
soldiers move and clouds drift between any two captures:
- **Pitch**: sky fraction stayed 0.138–0.153 across a −500 pitch *and* a +900 pitch. A working
  900-unit pitch down drives sky to ~0.
- **Translation**: the horizon landmarks sat at the same x (345, 460, 705, 795, 860, 930, 1075)
  before and after 90 `W` taps.
- Frame **hashes differed on every one of these** while the camera demonstrably had not moved.
  Never use a hash diff, or a "looks different" eyeball, as proof of camera motion.

Likely cause: the free camera orbits a target rather than flying free, so it ignores look input
and re-aims itself. `E`/`Q` still change altitude, which is why an ascended camera ends up
staring at the ground.

**Consequence: a wide/aerial shot, a legible station sign, and any specific framing require a
human at the keyboard.** The squad-follow spectator view *does* work under automation, but it
frames one soldier at a time. Plan visual verification around what one uncontrollable camera
plus `E`/`Q` can see, and hand the rest to the user rather than reporting it as proven.

`er2_look` / `er2_move_rel` / `er2_button` are kept because they are correct implementations of
relative motion and may drive other games or a future ER2 build — but they are **not** a working
ER2 camera control today. Absolute clicking remains correct for menus, the mission editor and
UI gizmos, which is where it has always worked.

## Procedure — do not skip the gates

1. **Deploy** — `er2_deploy(mission)`. It luajit-validates first; a FAIL means stop and fix
   the Lua, not press on.
2. **Launch** — `er2_launch()`, then `er2_state()`. Require `ready=1` AND `inner_alive=1`.
   A good screenshot is NOT proof the game is live.
3. **Get into the mission** — `er2_play_mission(map_row=N)` drives the editor and starts it, or
   navigate by hand with `er2_screenshot` + `er2_click(reliable: true)`. Re-screenshot after
   every step; never assume a click landed.
4. **Enter Free Camera** — the camera icon at the bottom-left of the in-world HUD. Confirm with
   a screenshot that the "Free Camera" title and the control legend are showing. The camera
   spawns roughly LEVEL, with the horizon across the middle — that starting framing is the most
   useful one you get, so capture it before touching anything.
5. **Altitude only** — `visual_probe.py ascend --steps N` (`E`) and `Q` to come back down are
   the ONLY controls that respond. Ascending tips the view toward the ground, so a high shot is
   usually a wall of dirt; if that happens, `Q` back down to recover the horizon.
6. **Do NOT expect `orbit` to turn the camera.** `orbit` issues correct relative-motion sweeps,
   but ER2 ignores them (see the table above), so its frames will all share one heading. It is
   retained for other titles and for re-testing after an ER2 update — if a future build DOES
   respond, re-verify with the sky-fraction and landmark-x methods above before trusting it.
7. **Reject empty frames** — `visual_probe.py contrast PATH` scores luminance mean/stddev and
   the unique-colour fraction, and **exits 1 on a visually empty frame**. `orbit` scores every
   frame as it goes. Several verification attempts have been wasted on captures that turned
   out to be featureless sand; a frame the tool calls EMPTY is not evidence and must not be
   reported as if it were. Re-ascend, re-orbit, or move the camera and capture again.

## What counts as proof

- **Proof**: a frame the contrast check calls USABLE, showing the specific thing claimed —
  soldiers in cover, a vehicle on a road, a captured objective — *plus* the corroborating
  `er2_log(tag="realistic"|"events")` lines from the same run. Two independent channels.
- **Proof**: several orbit frames agreeing, so the finding is not one lucky camera angle.
- **NOT proof**: a frame scored EMPTY. A featureless one is indistinguishable from a broken
  camera, a failed load, or nothing having spawned.
- **NOT proof**: two frames that are pixel-identical after a look command — that is the
  absolute-warp bug above, i.e. evidence the camera never moved, not evidence of stillness.
- **NOT proof**: a screenshot alone, with no log corroboration, and no `inner_alive=1` check.

Report what is visibly true, the frames that back it, and anything the contrast gate rejected
and why — a rejected frame is a result, not something to quietly retry until it passes.
