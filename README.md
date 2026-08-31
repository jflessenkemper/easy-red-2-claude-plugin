# easy-red-2 — a Claude Code plugin for driving Easy Red 2

An MCP server that runs **Easy Red 2** headless inside a gamescope harness and lets Claude drive
it: deploy Lua mods, start missions, click menus, screenshot, read the log, and run Lua in the
in-game console.

It exists because tuning game AI blind is guesswork. This was built to develop
[Realistic](https://github.com/jflessenkemper/easy-red-2-realistic), a WW2 soldier-AI mod, and
every feature here earned its place by making some specific mistake impossible to repeat.

**Headless and non-intrusive.** The game runs in its own gamescope compositor with a `headless`
backend — no host window, no stolen cursor, no stolen keyboard. You can work while it runs.

---

## Install

```bash
git clone https://github.com/jflessenkemper/easy-red-2-claude-plugin
```
Then in Claude Code: `/plugin marketplace add <path-to-clone>` and install **easy-red-2**.

The MCP server is registered by `plugins/easy-red-2/.mcp.json` and runs as
`python3 ${CLAUDE_PLUGIN_ROOT}/tools/er2_mcp/server.py`.

## Requirements

| Need | Detail |
|---|---|
| Easy Red 2 | installed via Steam (Linux) |
| gamescope harness | a gamescope fork exposing a Unix control socket. Set `ER2_HARNESS_BIN` if it is not auto-found |
| `luajit` | used by `er2_deploy` to syntax-check Lua *before* copying it into a mission |
| Steam Launch Options | **only for DLC missions** — see *Two launch modes* below |

Overridable env vars: `ER2_HARNESS_BIN`, `ER2_HARNESS_SOCK`, `ER2_GAME_DIR`, `ER2_CFG_DIR`,
`ER2_MOD_SRC`, `ER2_APPID`, `ER2_TMP`, `ER2_NULL_SINK`.

---

## Two launch modes, and what each one costs you

This is the single most important thing to understand before using the plugin.

| | `via_steam: true` *(default)* | `via_steam: false` |
|---|---|---|
| Needs Steam Launch Options wrapping `%command%` | **yes** | no |
| Runs inside the harness | yes (Steam injects it) | yes (the plugin runs it directly) |
| **DLC entitlement** | **yes** | **no** |

Steam only issues a proper app ticket through the `%command%` path, and without that ticket the
game cannot see owned DLC. A DLC map then appears in the Mission Editor as a dead
`Needs DLCs: <name>` row that highlights but never opens — with **no error and no log line**, and
non-DLC maps still working, which makes a launch-mode problem look mission-specific.

If the Launch Options are missing, `er2_launch` **fails immediately** and tells you how to fix it,
rather than waiting out its timeout. Repair (close Steam first — it holds a write lock on
`localconfig.vdf` and overwrites edits on exit):

```bash
python3 tools/fix_steam_launch_options.py --apply     # dry-runs without --apply; backs up first
```

---

## Tools

### Running the game

| Tool | What it does | Limits worth knowing |
|---|---|---|
| `er2_launch` | Starts ER2 headless in the harness. `width`/`height`/`fps`/`mute`/`via_steam`/`timeout_s` | Preflights the Steam path and fails fast if Launch Options lack the harness. `mute` routes audio to a null PulseAudio sink |
| `er2_stop` | SIGTERMs the game then the compositor | **Waits for teardown** before returning, and clears a stale socket — an immediate relaunch used to hit `ConnectionResetError` |
| `er2_state` | Harness state: `pid`, `uptime_ms`, `ready`, `inner_pid`, `inner_alive` | `inner_alive=0` means the game exited; relaunch |

### Driving menus

| Tool | What it does | Limits worth knowing |
|---|---|---|
| `er2_play_mission` | One call: Mission Editor → map row → mission → Edit → Sigma → Save/Play → Play | **Verifies its own end state** and reports `VERIFIED playing`, because a swallowed Play click is indistinguishable from success — phase scripts execute in the editor too, so log activity is *not* proof of play |
| `er2_click` | Click at screenshot pixel coordinates (1:1 at 1920×1080). `reliable=true` for stubborn UI | Coordinates are resolution-specific |
| `er2_key` / `er2_type` | Tap a key by friendly name or VK code / type a literal string | US-ANSI mapping; unmappable characters are skipped |
| `er2_screenshot` | Current frame, returned inline | The only honest way to know what the game is showing |

### Working with the mod

| Tool | What it does | Limits worth knowing |
|---|---|---|
| `er2_deploy` | **luajit-validates first**, then copies the mod into a mission: brains → `scripts/AI/`, phase script → `scripts/mission/phase_0.lua` | A file failing syntax check is never copied. Optional sources `SKIP` when absent rather than aborting |
| `er2_missions` | Lists missions and which mod scripts are deployed in each | |
| `er2_log` | Reads `Player.log` filtered by tag: `realistic`, `events`, `bench`, `errors` | |
| `er2_lua` | Runs a Lua snippet in the in-game F3 console — the live-tuning channel, no restart needed | Needs the game in a state where F3 opens; long snippets can time out |

---

## Traps this plugin knows about

Each of these cost real debugging time and is now either prevented or documented in
[`docs/ui-map.md`](docs/ui-map.md).

- **The phase script is not reloaded per battle.** Starting a second battle in the same process
  keeps the *old* phase script. Its 1 s loop is dead by then while its event callbacks still fire,
  so the kill feed and tally keep working and it looks healthy. **After changing a phase script,
  restart the game.** Proof of a real reload is a fresh `initial brain sweep` line.
- **Log activity is not proof of play.** Phase scripts run in the Mission Editor. ~7–9 decision
  traces/second means a real battle; ~2/s means you are watching an editor preview.
- **Free Camera** is the camera icon on the spawn menu. `X` hides the GUI, `E`/`Q` raise/lower,
  and it has Pause and Speed controls. **WASD does not translate.** Its `BACK` button returns to
  the squad-select screen — that is the spawn path, and the only way to test anything needing a
  player HUD, since Free Camera is a spectator and renders no HUD.
- **Windows-only Workshop mods.** A subscribed mod shipping only `StandaloneWindows64` bundles
  can never load on Linux. It produces `Failed loading mod (2)` plus a `NullReferenceException`
  every time a soldier wearing its assets despawns — which reads as a mod bug and is not one.

## Testing

```bash
tests/check.sh
```
Syntax, **names referenced but never defined or imported** (`py_compile` cannot catch those —
they are runtime lookups, and two shipped inside one function), every advertised tool actually
implemented, paths quoted in error text actually existing, and valid manifests.

`tools/analyse_run.py` is the behavioural gate: it cross-tabulates each AI decision against real
soldier displacement, because *a decision in the log is not proof of behaviour*.

## Licence

MIT. Easy Red 2 is a game by Corvostudio; this is an unofficial community tool, not affiliated
with or endorsed by Corvostudio.

## Watching the battle — `er2_map`

Decision counts tell you a branch fired. They cannot tell you whether the battle *looks* right: a
label will not show you a section strung out along a road, men bunching behind a halftrack, or one
soldier left standing in the open after everyone else went to ground.

`er2_map` renders the mod's telemetry into a single self-contained HTML page — every soldier and
every vehicle, positioned, scrubbable through the whole action:

- **the time slider rides on a strength curve** of both sides, so you jump to where the fighting
  was instead of hunting blind
- **colour by side, by height, or by decision** — height reads the terrain (river flats against the
  railway embankment); decision groups behaviour into families, so advancing, holding, pinned and
  medical each read at a glance
- movement trails, a 100 m grid at true scale, and per-frame counts of both sides, suppressed and
  down

It reads the `[TELEM]` frames the mod logs when `TELEMETRY = true` in `RealisticEvents.lua`. The
mod **ships that false**, so enable it, `er2_deploy`, and run the battle you want to watch.

Measured on Donchery: ~90 frames over ~13 minutes, 391 entities at peak, 99 vehicles named —
including emplaced weapons and aircraft.

### `movement_audit.py`

The numeric companion. It answers what the map shows you qualitatively:

- speed, milling, teleports and frozen soldiers, per side
- **intent versus outcome** — median speed *per decision*, so a move order that produces no
  movement is caught directly. That failure has happened for real here: defenders were issued
  `moveTo` orders they silently ignored.
- formation **per squad**, across versus along the axis of march — the only direct test of whether
  men actually march in file rather than as a blob
- nearest-neighbour spacing with **mounted troops excluded**, because men in a vehicle all report
  the vehicle's position and an unfiltered figure is dominated by them
