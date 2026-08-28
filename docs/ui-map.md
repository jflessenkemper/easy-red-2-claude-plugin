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

### Gotcha — direct launch hides DLC entitlements **[V]**

Launching the game binary directly with `SteamAppId` set runs the **base game fine** but the
process cannot see DLC ownership: owned DLC missions still show `Needs DLCs: …`. Observed with
Stonne (`Needs DLCs: Ardennes`) on an account that owns and has played it.

**Fix:** launch through Steam's `%command%` wrapper via Steam launch options, so Steam issues a
proper app ticket. Requires quitting Steam first (it holds an exclusive write lock on
`localconfig.vdf`). Same failure mode is documented for the AoE3 harness.

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
