# Easy Red 2 — UI map (v2.0.9, 1920×1080 harness)

Coordinates are **full-resolution 1920×1080** and are 1:1 with `er2_screenshot` pixels when the
harness runs at `-W 1920 -H 1080`. Screenshots are usually downscaled for reading; multiply
small-image coords by `1920 / <small width>` (e.g. ×1.92 for a 1000 px capture).

Status legend: **[V]** verified in-game by clicking it · **[O]** observed on screen, not yet clicked.

---

## Screen 1 — Startup

| Element | Action |
|---|---|
| "Press Space or Start" | `er2_key("space")` — **[V]** advances to the main menu |

**Gotcha [V]:** keys sent while the loading bar is still filling are silently dropped — the
harness returns `OK` (it injected at the compositor) but the game ignores them. Always confirm
with a follow-up screenshot; do not trust the `OK`.

## Screen 2 — Main menu

Version string "2.0.9" renders top-left. Left column, bottom group:

| Element | Coords (1920×1080) | Status |
|---|---|---|
| CAMPAIGNS | ~(180, 674) | [O] |
| MULTIPLAYER | ~(182, 747) | [O] |
| MISSION EDITOR | **(204, 820)** | **[V]** |
| SETTINGS | ~(159, 891) | [O] |
| EXIT | ~(127, 964) | [O] |
| CREDITS / STATISTICS / ROADMAP / DISCORD | top-left stack, y ≈ 184/244/303/363 | [O] |

## Screen 3 — Editor hub

| Element | Coords | Status |
|---|---|---|
| MAP EDITOR (left panel) | ~(530, 403) | [O] |
| MISSION EDITOR (right panel) | **(1392, 403)** | **[V]** |
| OPEN WORKSHOP MISSIONS | ~(404, 758) | [O] |
| OPEN WORKSHOP MAPS | ~(963, 758) | [O] |
| FORCE DOWNLOAD SUBSCRIBED WORKSHOP ITEMS | ~(1533, 758) | [O] |
| BACK | ~(88, 1014) | [O] |

## Screen 4 — Mission list (right-hand panel)

| Element | Coords | Status |
|---|---|---|
| "Local" tab | (1359, 23) | [O] |
| "Workshop" tab | (1726, 23) | [O] |
| Mission row 1 | (1544, **79**) | **[V]** selects (row turns olive) |
| Mission row 2 | (1544, **131**) | [V] *before* any expansion |
| Mission row 3 | (1544, ~182) | [O] |
| CREATE MISSION | ~(261, 77) | [O] |
| BACK | ~(88, 1014) | [O] |

**Row pitch ≈ 52 px** at 1920×1080.

### Gotcha — rows SHIFT when a mission is selected **[V]**

Selecting a mission that has unmet requirements **inserts a sub-row beneath it**
(e.g. `Needs DLCs: Ardennes`), pushing every later row down by one pitch. Cached
coordinates go stale the moment anything is selected.

**Rule: after any click in this list, re-screenshot and re-locate rows before clicking again.**

### Gotcha — DLC-locked missions cannot be opened **[V]**

A mission whose DLC you don't have (or that the process can't *see*, below) only ever
highlights — clicking, double-clicking and Enter all do nothing, and **nothing is written to
`Player.log`**. The only on-screen signal is the `Needs DLCs: <name>` sub-row.

### Screen 5 — Mission properties dialog **[V]**

Clicking a **mission** row (the sub-row under a map) opens a modal:

| Element | Coords | Status |
|---|---|---|
| **Edit mission** | **(960, 371)** | **[V]** — opens the editor on the map |
| Share on Steam Workshop | (960, 424) | [O] |
| Steam Workshop legal agreement | (960, 477) | [O] |
| "Tie to workshop map" dropdown | (1035, 543) | [O] |
| Name / Save ID / Previous ID fields | (1035, 662 / 710 / 767) | [O] |
| Save quick edits | (960, 821) | [O] |
| Delete mission | (960, 888) | [O] |
| Close (×) | (1280, 187) | [O] |

Map load after **Edit mission** takes ~45–75 s; `ready` stays 1 the whole time, so poll by
screenshot, not by STATE.

### Screen 6 — Mission editor (3D) **[V]**

Control bar (top) documents the bindings — verified on screen:

| Key | Function |
|---|---|
| **X** | Hide / show GUI |
| **Right mouse** | Look around |
| **E / Q** | Camera up / down |
| **Shift** | Camera speed |
| **Ctrl (hold) + mouse** | Camera zoom |
| **Space** | Quick camera movement |
| **Left mouse** | Select object |
| **P** | **Copy cursor position** ← the vec3 capture for waypoints/fire missions |

Bottom bar: phase selector (`◀ INITIAL PHASE ▶`, arrows at ~(825,1085) and ~(1110,1085)) and a
right-hand tool cluster at ~(1515 / 1605 / 1695 / 1785 / 1875, 1040) — briefing, units, sync,
objectives, weather-ish icons. Bottom-left `Σ` (~(35,1045)) opens the script/settings drawer.

### Gotcha — mission list is TWO levels **[V]**

Rows are **maps**; selecting a map expands its **missions** beneath it (e.g. Stonne →
"[Historical] Crossing at Donchery"). The DLC warning replaces that sub-row when entitlement is
missing, which is why it looked like "the mission won't open".

### Gotcha — direct launch hides DLC entitlements **[V]**

Launching the game binary directly with `SteamAppId` set runs the **base game fine** but the
process cannot see DLC ownership: owned DLC missions still show `Needs DLCs: …`. Observed with
Stonne (`Needs DLCs: Ardennes`) on an account that owns and has played it.

**Fix — VERIFIED to work:** launch through Steam's `%command%` wrapper via Steam launch options.
Run `tools/fix_steam_launch_options.py --apply` (Steam must be shut down first), then start the
game with **`xdg-open steam://rungameid/1324780`**. The resulting chain is:

```
AOE3DEHarness --keep-alive … --harness-socket $HOME/.er2harness.sock
└ gamescopereaper -- steam-launch-wrapper -- reaper SteamLaunch AppId=1324780
  └ pressure-vessel (SteamLinuxRuntime_soldier)
    └ Easy Red 2.x86_64 -force-vulkan
```

`reaper SteamLaunch AppId=…` is what grants entitlements. After this, DLC missions open normally.

### Gotcha — `steam -applaunch` does NOT work; use the `steam://` URL **[V]**

`steam -applaunch 1324780` from a shell silently does nothing (no process, nothing in
`~/.steam/steam/logs/console-linux.txt`). `xdg-open steam://rungameid/1324780` launches
reliably. Wait for Steam to be fully initialised first (≥3 `steamwebhelper` processes).

### Gotcha — VDF cannot escape quotes **[V]**

Steam's `localconfig.vdf` has no string escaping. Putting a **quoted** path into
`LaunchOptions` terminates the value early and silently splits it into an empty
`LaunchOptions` plus a bogus extra key — Steam then launches the game **unwrapped**. Always
write the path unquoted (emit a space-free shim if the real path contains spaces).

### Gotcha — socket must NOT live in /tmp **[V]**

Steam launches the harness in a different mount namespace from sandboxed tooling, which may
have a private `/tmp`. The socket then binds fine (`ss -lx` shows it LISTENing) but is
**invisible** to the client — indistinguishable from "harness not running". Put the control
socket in `$HOME` (`$HOME/.er2harness.sock`), which every party shares.

---

## Not yet mapped (blocked)

Everything past opening a mission is unmapped, because both local missions are DLC-blocked
under direct launch:

- Mission-editor canvas: object placement, camera controls, the **P**-key world-position copy
- **Squad Spawner properties — including the `Brain` field**, the single most important control
  for the Realistic mod (an empty Brain field silently means every soldier runs base AI)
- Save / Play-test flow
- In-game F3 Lua console (the `er2_lua` live-tuning path)

Unblock order: Steam launch-options fix → open Stonne → map the spawner panel → map F3.

### Gotcha — editor GUI toggle + transform mode **[V]**

Selecting an object enters a transform sub-mode: the top bar switches to
`Quick transform / 5-6 Elevate / Z Drag / 0 Reset transform` and the normal editor bars are
replaced. **X** toggles the whole GUI, and it is easy to lose track of parity — pressing it
blind can leave you with no toolbars at all (only the "MISSION EDITOR" watermark).
Escape opens the PAUSE menu (Settings / Resume / **Exit**) — `Resume` is at ~(1804, 886);
do NOT click Exit by accident.

**Recommendation:** do not drive the editor GUI to attach brains. Use the script path instead
(below) — it is deterministic and needs no clicking.

### DISCOVERY — the Brain field is not required at all **[V, high value]**

`Soldier.setBrain(file)` works at runtime, and `soldier_spawned` fires for every unit. So the
phase script can attach the AI brain to **every** soldier itself:

```lua
er2.setCallback("soldier_spawned", function(s) s.setBrain("Realistic.lua") end)
local sol = {}; er2.getAllSoldiers(sol)
for _, s in pairs(sol) do s.setBrain("Realistic.lua") end   -- catch already-spawned units
```

This removes the single most common silent failure (an empty Squad Spawner `Brain` field means
every soldier runs base AI), covers reinforcements that a spawner field would miss, and needs
no editor interaction whatsoever. Implemented in `RealisticEvents.lua` as `AUTO_ATTACH_BRAIN`.
