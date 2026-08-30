# Changelog

All notable changes to the **easy-red-2** Claude Code plugin.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] — 2026-08-30

Reliability pass. Every item here replaces a failure that was silent, misleading, or cost a
whole verification run.

### Added
- **`er2_launch` preflight for Steam mode.** Reads the game's Steam `LaunchOptions` and, if the
  harness does not wrap `%command%`, fails in about a second naming the cause, the repair
  command, and the direct-mode alternative with its DLC caveat. Previously it waited out the
  full timeout (default 420 s) and returned `launch timed out after waiting`, which named
  neither.
- **`er2_play_mission` verifies its own end state**, reporting `VERIFIED playing`. A swallowed
  Play click was indistinguishable from success because phase scripts execute in the Mission
  Editor too, so mod log lines keep appearing. One entire analysis pass was run against a battle
  that never started.
- **`tests/`**, which the plugin did not have: `undefined_names.py` fails on a global referenced
  but never defined or imported — `py_compile` cannot see these, and two shipped inside a single
  function — plus `check.sh` for syntax, advertised-vs-implemented tools, error text pointing at
  paths that actually exist, and valid manifests.
- **README documents all 12 tools** with their real behaviour *and* their limits, both launch
  modes and what each costs, and the traps worth knowing.

### Changed
- **`via_steam` now defaults ON.** Without it the game gets no DLC entitlement, so DLC maps
  become dead `Needs DLCs: <name>` rows that highlight but never open — with no error and no log
  line, while non-DLC maps still work. Callers must now opt out explicitly.
- **`er2_stop` waits for teardown** and clears a stale socket before returning, instead of
  returning the instant SIGTERM was sent. An immediately following `er2_launch` used to fail with
  `ConnectionResetError`; reproduced three times in one session.
- **`analyse_run.py` measures pooled per-(soldier, label) speed** instead of contiguous segments,
  which systematically under-measured and produced false failures; adds a COVER class, because
  `findCover` RELOCATES a soldier so no speed threshold can judge it; and judges the approach
  march on **objective closure** rather than pace.

### Fixed
- `er2_stop` treated `BrokenPipeError` as an error when it means the teardown succeeded.
- `t_deploy` aborted when an optional source file was absent; optional sources now `SKIP`.

## [1.0.0] — 2026-08-28

First public release.

### Added
- **Headless game control.** `er2_launch` / `er2_stop` / `er2_state` run Easy Red 2 inside a
  gamescope-fork harness: no host window, no cursor grab, invisible to host screenshot tools.
- **Vision.** `er2_screenshot` returns the live frame INLINE as an image (full-res or downscaled).
- **Input.** `er2_click` (with the two-tap "reliable" recipe for scene-transition buttons),
  `er2_key` (friendly names or Win32 VK codes), `er2_type`.
- **Live Lua tuning.** `er2_lua` executes a snippet in the in-game F3 console — retune a running
  mission without restarting it.
- **Telemetry.** `er2_log` tails `Player.log` filtered to `realistic` / `events` / `bench` /
  `errors`, with `shapes:true` to aggregate a multi-megabyte log by message shape.
- **Safe deploys.** `er2_deploy` luajit-validates every script and refuses to copy one that
  fails; `er2_missions` lists mission-editor missions and what is deployed in each.
- **Skill** `/easy-red-2:playtest <mission>` — deploy → launch → observe → report, with gates.
- **Audio isolation.** `er2_launch` defaults to `mute: true`, routing game audio to a null sink
  via `PULSE_SINK` so a headless instance can never bleed sound over what you are playing.
- **Zero-config paths.** Steam library (incl. `libraryfolders.vdf` extra libraries), game dir,
  config dir and harness binary are auto-discovered; env vars override.
- **Docs.** `docs/ui-map.md` records verified menu coordinates and the UI gotchas found in-game.

### Known limitations
- The in-editor screens past the mission list are not yet mapped — blocked because a directly
  launched process cannot see DLC entitlements, so DLC missions will not open. Fix is to launch
  via Steam launch options (`%command%`); see `docs/ui-map.md`.
- Requires the gamescope-fork harness binary providing the control socket; stock `gamescope`
  has no control socket.
- Linux/PipeWire only.
