# Changelog

All notable changes to the **easy-red-2** Claude Code plugin.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
