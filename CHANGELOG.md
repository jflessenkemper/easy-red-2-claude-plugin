# Changelog

All notable changes to the **easy-red-2** Claude Code plugin.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.12.0]

### Added
- **check 22 — every script `hooks.json` points at must exist and be EXECUTABLE.** A hook whose
  command is not executable does not error; the hook simply never runs and the protection it was
  written for is silently absent. The existing executable check covered only `bin/er2`. This is the
  same shape as the failure where the Steam guard was written, unit-tested and described as
  protection for a full day while the plugin containing it was not installed — nothing should be
  able to LOOK enforced while being dormant. Verified red by removing the executable bit.

## [1.11.0]

### Fixed
- **`play_mission` silently failed at any resolution other than 1920×1080, and misreported the
  cause.** Every click coordinate in it was derived by hand against the 1920×1080 UI. Run at
  1280×720 the navigation never left the MAIN MENU, and the tool blamed *"the mission panel was
  probably not open"* — sending you after a UI bug that does not exist. A wrong-but-plausible
  error message is worse than no message. It now reads `internal_w`/`internal_h` from the harness
  and refuses, naming the actual size, with `force_resolution: true` as the escape hatch.

  It refuses rather than scaling on purpose: ER2's layout is not uniformly proportional (some
  chrome is fixed-size), so a scale factor is a guess that would fail quietly in a *different*
  way — exactly the failure mode this evidence-driven tool exists to eliminate.
- **check 21** covers it in both directions — guard removed (must refuse and must not click) and
  guard too strict (must not block the calibrated size). A one-sided test would have been
  satisfied by refusing everything.

## [1.10.0]

### Added
- **`er2_launch` now REFUSES while another Steam game is running**, at two layers: the tool itself
  (`t_launch`) and the `PreToolUse` guard. `force: true` is the documented escape hatch, for when
  the user has explicitly said it is fine.

  This was learned destructively on 2026-09-13. Launching in `via_steam: false` mode was reasoned
  to be safe because it avoids restarting Steam — it is not. Without DLC entitlement, Steam pushes
  a **DLC store page through the overlay**, and the Steam overlay is **shared process-wide**: it
  attached to the user's foreground game, an **Ironman Bannerlord save**, and left a Vulkan-layer
  input grab (`ENABLE_VK_LAYER_VALVE_steam_overlay_1`) that survived killing `gameoverlayui`. The
  game had to be restarted. Steam mode is no better — it needs launch options, which needs Steam
  shut down, which closes their game outright. **There is no safe mode; only waiting is safe.**
- **check 20** covers the tool-level refusal, and **check 12** gained six conditional cases so
  non-launch commands (`er2 state`, `er2 screenshot`) keep working during someone else's game.
- `running_foreign_appids()` in `server.py`, verified to agree with `virtual_pad`'s scan.

### Fixed
- **check 20 could launch the game.** It calls `t_launch` for real, so a regressed guard meant
  running the test suite would start the game — the precise harm under test, and it happened once
  while verifying the check. The spawn path is now poisoned before the call, so a regression fails
  loudly instead of launching.

## [1.9.0]

### Added
- **`bin/er2` — a shipped command-line front end.** `bin/` goes on PATH when the plugin is
  installed. This work had been happening through an **unversioned shim in a scratchpad
  directory**, which is exactly how a second, subtly-wrong copy of "launch the game" gets born.
  It calls the same `t_*` functions the MCP tools call, so there is one implementation. Accepts
  either a JSON object or `--key value` pairs, prints MCP content blocks as plain text, summarises
  image blocks instead of dumping base64, and fails with a readable message rather than a
  traceback when the harness is down.
- **`visual_probe.py crop`** — crop and magnify a SAVED frame. The harness `SCREENSHOT_REGION`
  verb grabs a FRESH live frame, so it silently answers a different question when you are
  inspecting a past capture. Magnifying a saved frame is how the station landmarks were confirmed
  to be trucks rather than soldier clusters.
- **check 18** (CLI is executable, lists its tools, errors loudly on an unknown one, `--help`
  works with no harness) and **check 19** (crop scales a saved frame correctly and refuses an
  out-of-bounds box).

### Fixed
- `crop` referenced an undefined `TMP`, which would have raised `NameError` the first time anyone
  omitted `--out`. The crop test passed regardless because it always supplied one — **check 2
  caught it**, which is precisely the runtime-name class `py_compile` cannot see.

## [1.8.0]

### Added
- **`agents/playtest-runner.md`** — a subagent for long unattended play-tests, carrying the rules
  that have cost this project the most time (wait on log EVIDENCE not wall-clock; absence of log
  lines is not absence of behaviour; a count is not behaviour).
- **`commands/`** — `/er2-status` (harness, Steam, leftovers, and whether it is safe to touch
  Steam), `/er2-record` (clip + contact sheet, with the pixel-area frame-rate rule), and
  `/er2-restore` (put the machine back to normal, verifying each step).
- **Stop guard now catches leftovers that outlive the session**: a live `ER2 Virtual Pad` on
  `/dev/input/js0`, and stale `--keep-alive` harness processes. Both actually happened; both are
  invisible from inside the conversation.
- **check 13** exercises that guard (clean / stale-harness / escape hatch / no self-match),
  **check 14** validates skill, agent and command frontmatter, and **check 15** holds the
  README's manual-launch example against the tool's real flags.

### Fixed
- **The plugin was never installed.** Only `frontend-design` was enabled, so the MCP tools,
  skills, commands **and hooks** had never been active in any session — the Steam-shutdown guard
  was written, unit-tested and gated, but not wired in, so it could not have prevented the
  incident it was written for. The repo is now registered as a local `directory` marketplace.
- **`marketplace.json` advertised 1.0.0 against `plugin.json`'s 1.8.0** — the listing a user reads
  before installing was eight minor releases behind what they actually get. Gated by **check 16**.
- **`server.py` hardcoded `serverInfo.version = "1.0.0"`**, so the MCP `initialize` response had
  been reporting an untrue version for months. It now derives from `plugin.json`. **check 17**
  drives the real stdio protocol — `initialize` + `tools/list` — because checks 3 and 4 only
  imported the module, and a server can import perfectly while answering nothing.
- **The Stop guard exited early when no missions were deployed**, skipping the leftover checks
  entirely — so on a machine with nothing deployed, a live virtual gamepad or a stale harness
  would have sailed straight through. Only the BUILD scan is conditional now. Found by writing
  the test, not by reading the code.
- **The stale-harness scan matched its own caller.** Any shell command mentioning
  `AOE3DEHarness` — including the one testing the guard — carries the string in its own `/proc`
  cmdline, and excluding `$$` does not help because the offender is the PARENT shell. It now
  requires the process NAME to match as well. This is the same self-match trap that makes the
  full-cmdline forms of pgrep/pkill unusable in this project.
- **The plugin README documented the WRONG harness socket path** (`/tmp/ER2Harness.sock`) in two
  places — the exact drift that check 10 guards against in code, so a reader following the docs
  would start a harness the MCP server cannot talk to. It also still advertised the old framerate
  cap. **check 15** now holds the README's launch example against the real flags, and caught a
  second stale occurrence immediately after the first was fixed.
- **`record.py` and `virtual_pad.py` were not in the gate's `PY_FILES`**, so the two newest tools
  had no syntax or undefined-name checking at all.
- Both skills now declare `name:`, and `playtest` declares `allowed-tools:`.

## [1.7.0]

### Added
- **`tools/record.py`** — records the game to BOTH an mp4 and a labelled contact sheet. Stills
  sampled seconds apart miss anything temporal (a 45s diorama reset, a medic crossing to a
  casualty); the clip captures the motion and the sheet is how an agent READS that motion, since a
  model can look at one tiled image but cannot watch a video. Frames come from `SCREENSHOT_BYTES`
  (inline over the socket, no per-frame disk round-trip); `--wait-log REGEX` starts the capture on
  a new matching log line rather than on a guessed delay. Measured capture rate is ~0.9 fps at
  1920x1080 headless.
- **`tools/visual_probe.py`** — `shot` / `look` / `orbit` / `ascend` / `contrast`. The `contrast`
  gate scores luminance and unique-colour fraction and **exits 1 on a visually empty frame**;
  several verification attempts had been wasted on captures that turned out to be featureless sand.
- **`tools/virtual_pad.py`** — a stdlib-only uinput Xbox-style gamepad, with a safety interlock
  that REFUSES to create the device while a Steam game other than Easy Red 2 is running. A virtual
  pad is globally visible and would disturb whatever the user is playing.
- **`skills/visual-test/`** — the procedure for visually proving mod behaviour, and the measured
  record of which input paths reach ER2's camera.
- **MCP tools `er2_button`, `er2_move_rel`, `er2_look`, `er2_drag`** — the harness had implemented
  `BUTTON` and `DRAG` all along without exposing them; `MOVE_REL` / `LOOK` are new.

### Changed
- **`record.py --region X,Y,W,H` raises the capture rate ~15x** (0.9 -> 14.0 fps measured).
  Capture cost is proportional to PIXEL AREA: full 1920x1080 ~660 ms, a 640x360 region ~69 ms
  (9.0x fewer pixels, 9.6x faster). The bottleneck is per-pixel readback, not the socket
  round-trip and not the encoder -- PNG measured FASTER than JPEG. Region capture is always PNG
  because the harness rejects any other extension.
- **Harness now runs at `-r 60 --framerate-limit 60`** (was 30), so the source is smoother.
- **`tools/fix_steam_launch_options.py` now passes `--force-grab-cursor`.** Without it the
  compositor flips between absolute and relative mouse mode on cursor visibility and settles on
  absolute.

### Notes
- **x11grab does not work** for this game. It renders through gamescope's compositor, so the
  nested Xwayland root window is solid black (verified: mean 0.0 -- the empty-frame gate caught
  it). The compositor screenshot path is the only real pixel source. Beware `DISPLAY=:0` in the
  game's environment: that is the USER'S OWN desktop, inherited from the host, not the harness.
- ER2's Free Camera **cannot be aimed** by this harness. Absolute warps, true relative motion,
  relative-with-button-held, `--force-grab-cursor` and a uinput gamepad (created both before and
  after game launch) were all measured as having no effect. Only `E`/`Q` altitude responds.
- What DOES work for touring the map: the squad-follow spectator plus **LEFT/RIGHT arrows to cycle
  squads**, **SPACE** for the squad role list, and clicking a role to **deploy first-person**,
  after which **`M`** opens the tactical map.

## [1.6.0]

### Added
- **`hooks/hooks.json` — the operational rules are now ENFORCED, not documented.** Both guarded
  rules were broken for real on 2026-09-08: a `pkill -9` destroyed the Steam login session and
  blocked the whole task, and a mute loop over every sink-input silenced the user's other game
  *and* a live voice call. A `PreToolUse` guard on Bash now refuses force-kills aimed at Steam and
  refuses `@DEFAULT_SINK@` mutes / all-sink-input sweeps, with the reason on stderr so the refusal
  teaches rather than just fails. A `Stop` guard refuses to end a session while a diagnostic build
  is still deployed. Gated by check 12, which drives the guard with 6 dangerous forms (must block)
  AND 5 legitimate lookalikes (must allow) — `steam -shutdown` and killing our own harness have to
  keep working.
- `alwaysLoad: true` on the MCP server so its tools are not deferred behind a `ToolSearch` call
  every turn. NOTE: the documented examples for this field are `http`/`ws` servers; ours is
  `stdio`, so this is unverified for stdio and harmless if ignored.
- `timeout: 600000` (10 min) — `er2_launch` and `er2_play_mission` both exceed the 2-minute
  auto-background threshold, and that backgrounding is disabled in non-interactive mode.
- `_meta` `anthropic/maxResultSizeChars: 500000` on `er2_log`. `Player.log` runs to tens of
  megabytes and the default result threshold is 25,000 tokens — a truncated tail is how you
  conclude "no errors" from a log that was cut before the errors. Deliberately NOT applied to
  `er2_screenshot`: image data stays bound by `MAX_MCP_OUTPUT_TOKENS` and cannot be raised this
  way, so that limit is documented instead of pretended away.
- `$schema` on the manifest for editor validation.

### Fixed
- `docs/ui-map.md` is now shipped INSIDE the plugin. Tool descriptions cited it three times while
  it existed only at repo root, so an installed plugin pointed users at a file it did not ship.
  Gated by check 11.

### Notes
- Tool descriptions were audited against the 2KB truncation limit: the largest is 489 chars, so
  that risk does not currently apply.

## [1.4.0] — 2026-08-30

### Fixed
- **Reverted the all-phases deploy from 1.3.0; `er2_deploy` installs `phase_0.lua` only again**
  (`phases` is now opt-in, default 1). Installing the script for later phases revives nothing —
  the phase change is what kills the old phase's coroutine — and it *introduces* an engine fault:
  `Lua error at 'phase_1.lua': Object reference not set … BattleManager:TryExecutingPhaseScript()
  / OnPhaseChange(Int32) / NextPhase()`. Runs before that change had zero exceptions of any kind.

### Documented
- **`docs/ui-map.md`: corrected the phase-loop write-up and recorded the real cause.** Per-tick
  tracing shows the last line the loop ever logs is `trace tick=47 pre-sleep` with no matching
  `post-sleep` — the body completes and **`sleep(1)` never returns**, because ER2 implements sleep
  as a Unity coroutine and the Lua coroutine is abandoned mid-sleep when `OnPhaseChange` fires.
  The earlier "dies at objective capture / the phase never advanced" conclusion was wrong: capture
  is a correlate, and the missing `initial brain sweep` only showed the NEW phase's script failed
  to load, not that no phase change occurred. **A missing marker is not evidence of a missing
  event** — worth remembering, it is the second time that shape of mistake has cost a diagnosis
  here.
- The mod fixes it internally with a watchdog on `soldier_died` (a callback the engine keeps
  firing), verified live: attraction output kept growing while the loop's tick stayed frozen, with
  zero errors.

## [1.3.0] — 2026-08-30

### Added
- **`er2_deploy` installs the phase script as every `phase_<n>.lua`, not just phase 0** (default
  8, `phases` to change). ER2 runs the script belonging to the CURRENT phase, so a mission that
  advances past phase 0 with only `phase_0.lua` present has no phase script at all from then on.
  Each copy reads `MY_PHASE` at load and self-identifies; copies for phases a mission does not
  have are never loaded.

### Documented
- **`docs/ui-map.md`: the phase-script loop dies at OBJECTIVE CAPTURE**, with the evidence table.
  Measured twice on Donchery: loop-driven output stops (run 1 at log line 22266 of 70609, run 2 at
  15742 of 85183) while `soldier_died` output continues all battle, which is why it has always
  looked healthy. Three earlier diagnoses are ruled out by evidence — no `LOOP BODY ERROR` ever
  logged, the phase never advanced (so it is not phase teardown, and the all-phases deploy above
  did not change it), and `global` IS shared brain→phase (the phase read the brain's
  `PROBE_B2P=4242`). Control: VirtualScene never captures anything and its loop ran 106+ cycles.
  The remaining suspect — `sleep()` being a Unity coroutine that stops being resumed — is recorded
  as a hypothesis, explicitly not as cause, because no exception appears anywhere in the log.
- **A sampling trap worth knowing:** the first `gprobe` line reads `nil` because it runs before any
  brain has started. Sampling it once and concluding "globals are not shared" was nearly written up
  here as fact.

## [1.2.0] — 2026-08-30

Findings pass. Both entries below are traps that presented as "the tool is broken" or "the game
is just slow", and each cost real time before being understood.

### Added
- **Workshop-integrity preflight.** A Workshop item that Steam lists as installed but whose
  content directory is missing throws inside the editor hub's enumeration, killing the loading
  coroutine: the hub sits on *"LOADING Workshop campaigns"* forever, the mission list never
  renders, and `er2_play_mission` cannot work. There is no error dialog and the game stays
  responsive, so it reads as slowness. `er2_launch` (both modes) and the `er2_play_mission`
  failure path now diff `WorkshopItemsInstalled` against the directories actually present and
  warn with **every** missing id — the game's own log names only the first, because the
  enumeration aborts there. Items sidelined as `<id>.disabled` are called out with the exact
  rename that undoes it. Warning only, never a block: only the editor hub is affected.

### Changed
- **Direct-mode launches now state the DLC consequence up front**, instead of leaving it to be
  rediscovered when a mission will not open. Confirmed on-screen this time rather than inferred:
  a DLC-gated map's mission sub-row is replaced by an inert `Needs DLCs: <name>` label. SteamAPI
  *does* initialise in direct mode, so a successful Steam init is not evidence of entitlement.
- **`er2_play_mission`'s failure text names both silent causes** — a hung Workshop enumeration
  and a DLC-gated map — rather than only suggesting manual clicks.

### Fixed
- **The Steam LaunchOptions reader picked the wrong match and reported the options as empty.**
  The app id appears many times in `localconfig.vdf`, mostly inside base64/hex token blobs on
  lines like `"1324780"  "3e0000..."`. Taking the first raw occurrence landed in one of those,
  found no `LaunchOptions` nearby, and concluded there were none - so the preflight told the user
  to run a repair they had **just successfully run**, and refused to launch. It now matches the id
  as a KEY (alone on its line) and falls back to a loose scan, so a genuinely empty entry is still
  reported as empty.
- **`er2_play_mission` blamed deployment for a silence it should expect.** The mod ships with
  `DEBUG = false`, which gates every diagnostic line, so a correctly deployed *shipping* build is
  silent and the "initial brain sweep" marker can never appear. The tool said "no mod output at
  all - is the mod deployed?", sending you to re-deploy something already correct. It now detects
  a deployed `DEBUG = false` and says the check cannot confirm play either way, which is the
  honest answer.
- **`er2_play_mission`'s failure text now names the splash screen first.** It assumes the main
  menu; on "Press Space or Start" every click is swallowed while all navigation steps still
  report OK. That exact sequence wasted two full mission-load attempts.

### Documented
- `docs/ui-map.md`: the Workshop hang; mission-list rows are **toggles**, so they need
  `{"reliable": false}` (a double-click expands then collapses, which looks identical to the
  mission failing to open); `Needs DLCs: <name>` as the definitive DLC signal; and why neither
  non-DLC local mission can substitute for Donchery when verifying AI behaviour.
- Two counting traps that nearly became false bug reports: `initial brain sweep: 0 soldier(s)` is
  correct (the phase script loads before anyone spawns), and the `brain attached to N` line is
  sampled, so it is silent between 4 and 24 and is not an attach count.

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
