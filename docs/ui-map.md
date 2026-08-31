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

## SOLVED — how to play a custom mission **[V]**

**It is inside the editor, in the save panel** — not in Campaigns, not in Multiplayer, not in
the mission-properties dialog (all three verified to lack it).

Editor → bottom-left `Σ` (49, 1044) opens a drawer with a bottom toolbar:

| Icon | Coords | Panel |
|---|---|---|
| ☰ | (49, 1044) | Battle settings: name, gamemode, factions, tickets, max concurrent |
| 📍 | (134, 1044) | objectives / markers |
| ☀ | (216, 1044) | weather / time |
| 👥 | (298, 1044) | units / squads |
| **💾** | **(380, 1044)** | **Save · Play · Play from current phase · Difficulty · Guide** |
| `</>` | (463, 1044) | Scripting: Scripting Guide, **Manage AI scripts**, **Id tables**, localization, Mission ID |
| ❰❰ | (636, 1044) | collapse drawer |

Save/Play panel buttons: **Save** (300, 108), **Play** (300, 183),
**Play from current phase (N)** (300, 258), Difficulty (300, 333), Guide (300, 450).

`</>` → **Manage AI scripts** (300, 192) opens a "Script editor" listing the mission's AI
scripts with a *New script* name box + Create. Scripts dropped into the mission's
`scripts/AI/` folder on disk show up here. **Id tables** (300, 274) is the in-game enum
reference (VoiceClip etc.).

## Still unmapped
- Squad Spawner properties panel (the `Brain` field) — **no longer on the critical path**: the
  phase script now attaches brains itself via `setBrain`, see the discovery note above.
- In-game F3 Lua console (the `er2_lua` live-tuning path) — needs a running match.
- Editor object list / how to locate a specific spawner without hunting in 3D.

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

### Screen 7 — CREATE MISSION → map picker **[V]**

Mission list → **CREATE MISSION** (261, 77) opens a map picker:

| Element | Coords | Status |
|---|---|---|
| Search box | (1075, 143) | [O] |
| Source tabs: Vanilla / Local / Workshop | (700, 315 / 360 / 406) | [O] |
| **Virtual Scene** (first row) | **(1046, 219)** | **[V]** — flat grid, no DLC: ideal test bed |
| Map rows below | pitch ≈ 48 px | [O] |
| CANCEL | (697, 1000) | [O] |

Map rows carry a DLC badge on the right (e.g. Stalingrad, Normandy, Shanghai/Nanking).
Selecting a map creates the mission and loads the editor (~50 s).

### Custom missions are NOT playable from Campaigns or the mission dialog **[V]**

Checked all three: Campaigns lists official campaigns only (sidebar ends at
"Operation Spring Awakening"); Multiplayer → Create Match shows the official campaign
browser; the mission-properties dialog has Edit/Share/Quick-edit/Delete but **no Play**.
The play path for a custom mission is still unidentified — pending.

### Saving a NEW mission has prerequisites **[V]**

Save refuses with a red modal until both are satisfied (OK button at (960, 618)):

1. **"Battle name not setted!"** — set it in the `☰` settings panel: click the battle-name
   field at (305, 46) and type. (The harness has a native `TYPE <text>` command — it works and
   is far better than per-character VK keys.)
2. **"First phase not setted up!"** — the initial phase needs objectives/spawns placed in the
   3D view before the mission can be saved or played.

So a mission cannot be created purely from the outside: the first phase requires in-editor
placement. Scripts alone (even `spawnSquad_script`) cannot bootstrap a brand-new mission,
because the mission will not save without a configured first phase.

## VERIFIED LIVE — full play-test through the plugin (2026-08-28)

`er2_play_mission(map_row=2)` drove main menu -> editor -> Stonne -> "[Historical] Crossing at
Donchery" -> Play in ONE call, then faction selection. Results from the running battle:

- `brain attached to 350 soldier(s)` — the phase-script auto-attach replaces the Brain field.
- 10,731 `[REALISTIC]` decisions in one run; every cascade branch reachable:
  MOUNTED/CREW-defer 5458, ROAD-MARCH 5288, FIGHT-from-cover 348, PINNED 195,
  LEADER-cover 91, ADVANCE-behind-armour 47, RALLY-on-MG 31, REBOARD-transport 26,
  MEDIC-hold-cover 23, ASSAULT 9.
- Nation + role detection works on both sides: germany/france trooper, LEADER, medic, MG-gunner.
- Objective attraction drives capture: `obj1 inv=15 def=0 held=true <- CAPTURED by attackers`.
- After removing the soldier_suppressed subscription: **0 callback errors** (was 12+ per run).

## MEASURED BEHAVIOUR — are troops actually obeying orders? (2026-08-28)

Decisions in the log prove the brain is *deciding*, NOT that the game obeys. Verified by
parsing the `@(x,z)` in every trace line and computing per-soldier displacement:

- 363 soldiers traced; **310 moved** (path > 5 m), median path 62 m, max net displacement
  1397 m. So orders do reach the engine.
- Hold-type orders correctly produce no movement (PINNED 5 m, FIGHT-from-cover 2 m median).
- Mounted troops move furthest (389 m / 118 m median across runs) — base AI drives them.
- **Attackers move (122 m median); defenders do not (7 m median), regardless of the order
  issued.** Base AI keeps defenders on their defensive positions and overrides `moveTo`
  because `allowFollowOrders` is true. Relabelling the order (ROAD-MARCH -> DEFEND-move-up)
  changed nothing: 158 soldiers still averaged 6 m.
- Conclusion: this is correct for a defensive battle, so the brain no longer fights it —
  defenders hold and take cover unless absurdly out of position (`DEFEND_RADIUS`).

**Method worth repeating:** never accept "the log shows the decision" as proof of behaviour.
Diff positions over time and compare movement against the order class.

## A/B EXPERIMENT — does suppressing base-AI order-following help? NO (2026-08-28)

Question: is observed movement caused by OUR `moveTo`, or by base AI coincidentally agreeing?
Method: within a single battle, half the soldiers set `allowFollowOrders(false)` while an
override was active (and restored it on hand-back); the other half were untouched. Same map,
same fight, so the difference is attributable to the lever.

**Trap hit first:** `uid % 2` produced a degenerate split (control n=0). ER2 hands out unique
IDs with an **even stride** (observed 262 apart), so every uid is even. `(uid // 2) % 2`
alternates properly — verified 148/165 over 313 real uids before re-running.

**Result (n=133 suppressed vs 128 control):**

| group | suppressed | control | delta |
|---|---|---|---|
| overall | 6.8 m | 7.5 m | −9% |
| attackers | 14.5 m | 13.0 m | +11% |
| defenders | 3.2 m | 3.9 m | −17% |

All within noise. **Verdict: do not suppress base-AI order-following** — it buys nothing and is
marginally worse overall. Defenders stayed put in both groups (66% vs 56% stuck), confirming
their holding is base-AI behaviour that should not be fought. `AB_SUPPRESS_BASE_AI = false`.

## 2026-08-29 — er2_play_mission can report success while the game never enters play

**Symptom:** `er2_play_mission(map_row=2)` returned the full happy-path step list ending in
`clicked Play`, and `[REALISTIC]`/`[EVENTS]` lines DID appear in Player.log (brains attached,
tally incrementing) — but a screenshot showed the game still sitting in the **Mission Editor at
"Initial phase"**. Phase scripts execute in the editor, so log activity is NOT proof of play.
Decision traces trickled at ~2/s with only ROAD-MARCH / PINNED / MOUNTED-CREW-defer reachable,
and analyse_run.py returned a meaningless GATE: FAIL on 1-5 segment samples.

**Cause:** the Sigma -> Save -> Play chain is click-timing sensitive. Clicking Save at (380,1044)
opens a SUBMENU (Save / Play / Play from current phase (0) / Difficulty / Guide); the Play entry
sits at approximately **(300,184)**. If the submenu has not rendered when the Play click fires,
the click lands on the editor viewport and is silently swallowed. No error is raised.

**Working manual sequence (verified 2026-08-29), screenshot-verified between EVERY step:**
1. `er2_click (49,1044)`  -> Sigma panel (mission battle data: factions, max concurrent)
2. `er2_click (380,1044)` -> Save/Play submenu
3. `er2_click (300,184)`  -> Play; ~45 s load
4. `er2_click (864,884)`  -> FACTION SELECTION, left flag = Axis/attacker, right = Allies
5. Battle intro plays (title, date, commander briefing).
   **`escape` does NOT skip the intro — it opens the PAUSE menu.** Resume is at ~(1805,885).
6. After Resume, decision traces run at ~7/s (vs ~2/s in the editor) — this rate difference is a
   cheap liveness check for "actually playing" vs "editor preview".

**Rule learned:** never trust a navigation tool's own success report. Screenshot-verify the game
state before marking a log position, or you will analyse an editor preview and draw conclusions
from it. Log activity alone does not distinguish editor from play.

**Also observed:** in-game pause menu showed Music volume 0%, Master 25.2% — settings left
untouched deliberately (user's own audio config; harness handles muting via null PULSE_SINK).

## 2026-08-29 — er2_launch without via_steam silently loses DLC entitlements

**Symptom:** after `er2_launch` with default args, the Mission Editor map list showed `Stonne`
expanding to a single greyed row reading **`Needs DLCs: Ardennes`** instead of the mission. The
row highlights on click but nothing opens — no Edit button, no error, no log line.

**Cause:** `er2_launch` defaults to launching the binary directly. DLC entitlements only resolve
when the game is started **through Steam**, so every DLC map becomes unselectable while
non-DLC maps (`Realistic Test map`, `VirtualScene`) still work — which makes it look like a
mission-specific problem rather than a launch-mode problem.

**Fix:** `er2_launch {"via_steam": true}`. Confirms with
`launched via Steam (DLC entitlements available)`.

**Gotcha:** calling `er2_stop` immediately followed by `er2_launch` fails with
`ConnectionResetError: [Errno 104] Connection reset by peer` — the harness socket is still
tearing down. Sleep ~15 s between stop and launch.

**Rule:** if a known-good mission suddenly cannot be opened, check the launch mode before
suspecting the mission or the scripts. The symptom names the DLC, not the cause.

## 2026-08-29 — the phase script is NOT reloaded for each battle in one game process

**Symptom:** deploy a changed `phase_0.lua`, click Play, run a battle — and the new code does not
run. Event callbacks (`soldier_died` etc.) keep firing normally, so the script looks alive: the
kill feed works, the tally increments. But nothing from the 1 s `while true` loop appears — no
objective-attraction lines, no bail-out drain, no fire-mission consumption.

**Evidence:** across a 495k-line Player.log there are only **6** `initial brain sweep` lines (one
per phase-script LOAD), the last at line 446,818 — while battles continued past line 495,000.
Loop-sourced output (`invAttract`, `alive invaders=`) stops at line 462,427 and never resumes.

**Cause, two parts:**
1. The phase loop begins `if getCurrentPhaseId() ~= MY_PHASE then break end`. When a battle ends
   the phase changes, the loop breaks, and it never restarts.
2. Starting another battle in the SAME game process does not re-load the phase script, so the
   dead-loop instance persists — with its callbacks still registered, which is what makes it look
   healthy.

**Consequence:** a `deploy -> Play` cycle without a game restart can silently test STALE phase
code. Two verification runs were wasted this way.

**Rule:** after changing `RealisticEvents.lua`, RESTART THE GAME (`er2_stop`, wait ~15 s,
`er2_launch {"mute":true,"via_steam":true}`) before trusting the run. Confirm the reload by
checking for a NEW `initial brain sweep` line after your log mark — that line is the only
reliable proof the phase script actually re-loaded. Brain (`Realistic.lua`) changes do reload per
battle, because brains are re-attached to freshly spawned soldiers.

## 2026-08-30 — Steam LaunchOptions are the ONLY thing that makes Steam mode work

**The two launch modes are not interchangeable, and each loses something:**

| Mode | Needs Steam LaunchOptions? | Harness? | DLC entitlement? |
|---|---|---|---|
| `er2_launch {"via_steam": true}` (default) | **YES** — must wrap the harness around `%command%` | yes, injected by Steam | **yes** |
| `er2_launch {"via_steam": false}` | no — the plugin runs `HARNESS … -- GAME_BIN` itself | yes | **NO** |

So the harness works perfectly well with no launch options at all — but the game then gets no
Steam app ticket, every DLC map shows a dead `Needs DLCs: <name>` row, and a DLC mission simply
cannot be opened. Donchery is on Stonne, which needs Ardennes, so direct mode cannot test it.

**Failure mode when the options are cleared:** Steam launches the game bare, no harness socket
ever appears, and `er2_launch` used to sit for the whole `timeout_s` (default 420 s) and then
return `launch timed out after waiting`, naming neither the cause nor the fix.

**Fixed 2026-08-30:** `er2_launch` now PREFLIGHTS the Steam path. It reads `LaunchOptions` out of
`localconfig.vdf`, and if the harness does not wrap `%command%` it fails in about a second with
the cause, the repair command, and the direct-mode alternative plus its DLC caveat. Nothing is
launched.

**Repair:** close Steam first — it holds an exclusive write lock on `localconfig.vdf` and will
overwrite the edit on exit — then:
```
python3 <repo>/tools/fix_steam_launch_options.py --apply
```
It dry-runs by default, backs the file up, and refuses to run while Steam is open.

---

## 2026-08-30 — a missing Workshop item HANGS the editor hub forever **[V]**

**Symptom:** the editor hub sits on **"LOADING Workshop campaigns"** indefinitely. The mission
list never renders, so `er2_missions`' UI path and `er2_play_mission` cannot work. The game stays
fully responsive and shows no error dialog, so it reads as "slow" rather than "broken" — the first
attempt here was to just wait it out, twice.

**Cause:** the hub enumerates the Workshop items Steam believes are installed and opens each one's
content directory. A missing directory throws `DirectoryNotFoundException` *inside* the
enumeration, killing the loading coroutine.

```
DirectoryNotFoundException: Could not find a part of the path
  '~/.local/share/Steam/steamapps/workshop/content/1324780/<id>'
```

**Two traps in reading that log line:**
- The enumeration **aborts at the first bad item**, so the log names exactly ONE id even when
  several are missing. Do not treat it as the complete list.
- The item is still *subscribed*; only its content is gone. Deleting or renaming the directory does
  not unsubscribe it, so the game keeps trying.

**Cause seen here:** three Windows-only mods had been sidelined by renaming them to `<id>.disabled`
to stop them spamming errors. That quarantine is what broke the hub. Restoring all three
(`mv <id>.disabled <id>`) fixed it immediately — the hub then loaded clean on the next launch.
Other routes to the same state: an interrupted Steam download, or content deleted while subscribed.

**Fixed 2026-08-30:** `er2_launch` (both modes) and the `er2_play_mission` failure path now run
`_preflight_workshop()`, which diffs `WorkshopItemsInstalled` in `appworkshop_1324780.acf` against
the directories actually present and warns with every missing id — flagging any it finds as
`<id>.disabled` with the exact rename to undo. It is a WARNING, never a block: the game itself
boots fine and only the editor hub is affected.

**Fix for a user:** restore the directories, or unsubscribe the items in Steam so the game stops
enumerating them.

## 2026-08-30 — mission-list rows TOGGLE; never double-click them **[V]**

`er2_click {"reliable": true}` sends the click **twice** (it exists because some buttons swallow a
single click). Mission-list rows are toggles, so a "reliable" click expands the row and then
collapses it again — the row highlights but its sub-row never appears, which looks exactly like
"the mission failed to open". Two double-clicks in a row left it collapsed both times here.

**Rule:** map rows and mission sub-rows take `{"reliable": false}`. This is why `t_play_mission`
passes `reliable=False` for both list clicks and `True` almost everywhere else.

Selecting a map expands ONE sub-row beneath it (pitch 52), and that sub-row is one of:
- the mission name + belligerent flags → clickable, opens the mission dialog;
- `Needs DLCs: <name>` → **inert**, and the definitive on-screen signal that the map is DLC-gated.
  In direct-launch mode *every* DLC map shows this, so it is also how to confirm at a glance that
  the game has no entitlement.

## 2026-08-30 — picking a fallback test mission: what "playable" is not **[V]**

With DLC entitlement unavailable, the two non-DLC local missions were tried as substitutes. Neither
can verify AI behaviour, and both fail in ways that look like success at first:

| Mission | Loads? | Why it cannot verify behaviour |
|---|---|---|
| `VirtualScene` / "Testing" | yes | 6 v 6, **all AT class**, on a flat featureless plane; both sides lock into mutual `PINNED` at 14–21 m and never resolve. Deaths occur (`tally invaders:6 defenders:2`) but `alive` stays 6 v 6 — the mission **respawns**, so the battle never ends and no phase change ever happens. |
| `Realistic Test map` | no | `Needs DLCs: Hungary`. |

Two things that look like bugs here but are not:

- **`initial brain sweep: 0 soldier(s)` is normal.** The phase script loads *before* the battle
  spawns anyone, so the one-shot sweep legitimately finds nobody; every soldier is picked up
  afterwards by the `soldier_spawned` callback. A zero here is not a failure to attach.
- **`brain attached to 3 soldier(s)` being the last such line does not mean only 3 attached.** That
  log is sampled (`attached <= 3 or attached % 25 == 0`), so it is silent between 4 and 24.
  Likewise only ~1 soldier in 6 emits decision traces (`DBG_SAMPLE = 6`), so counting distinct uids
  in the log undercounts brains by design. Neither number is an attach count.

**Consequence:** confirming the phase-loop-across-a-battle-boundary question needs a mission that
actually ENDS. Donchery does; neither of these does.

## 2026-08-30 — the phase loop dies at OBJECTIVE CAPTURE (three fixes had the wrong cause) **[V]**

Measured live on Donchery, twice, with `DEBUG = true` and `PROBE_GLOBALS = true`.

**What actually happens.** Loop-driven output — `obj<N> inv=…`, `alive invaders=…`, `gprobe:` —
stops dead, while `soldier_died`-driven output (`tally`, `callout`) keeps going for the rest of the
battle. Run 2: last loop line **15742**, log grew to **85183**. Run 1: last loop line **22266**, log
grew to **70609**, and a radioman's fire-mission request at line **59018** was never answered.

**The correlation is objective capture, not time and not a phase change:**

| Mission | Objective captured? | Loop cycles before it stopped |
|---|---|---:|
| VirtualScene "Testing" | never (`held=false` throughout) | 106+, still running at the end |
| Donchery run 1 | yes | ~11 |
| Donchery run 2 | yes | ~11 |

**Three hypotheses are now RULED OUT by evidence, not by argument:**
1. *An unhandled error in the loop body.* The body is wrapped in a `pcall` that logs
   `LOOP BODY ERROR`. That line appears **zero** times.
2. *The engine tears the coroutine down at a phase change.* The phase never advanced — exactly
   **one** `initial brain sweep`, and `obj1` remained the only objective. Deploying the script as
   every `phase_<n>.lua` (now the default) did not change the outcome.
3. *`global` is not shared brain→phase.* Disproved directly: the phase script read the brain's
   `PROBE_B2P=4242`. Note the FIRST `gprobe` line reads `nil` simply because it runs before any
   brain has started — sampling it once and concluding "not shared" is a trap, and one that was
   nearly written up as fact here.

**What that leaves.** The loop's only unprotected statement is `sleep(1)`, which ER2 implements as
a Unity coroutine (`PauseForSeconds` → `pauseWithCallback` → `Coroutine_Resume`, visible in the
stack trace attached to every `log()` line). If whatever hosts that coroutine stops resuming it,
the Lua loop simply never continues: no error, no `idling:` line (the loop is gone before it can
run its own phase check), and engine-registered callbacks are unaffected because they live
elsewhere. The capture-time trigger points at the `setAttractor` call that fires when an
objective's attraction state CHANGES — the one code path a capture newly exercises — but that
specific call has **not** been isolated, and no exception of any kind appears in the log.

**Consequence for the mod — this is the honest status:**
- Objective attraction (feature 20) works until the first objective is captured, then stops.
- The fire-mission consumer (feature 19) and the bail-out queue drain share the loop, so they stop
  at the same moment. This fully explains why feature 19 has never logged an accept or a refusal
  in any session: by the time a radioman stalls long enough to call one in, the consumer is gone.
- Per-soldier brains are NOT affected. They are separate coroutines and keep running all battle —
  which is why the mod still behaves correctly in every visible respect.

**Do not** claim any of the four wait-and-resume fixes as verified in-game. They are correct as
logic (the offline harness drives them), but the loop they protect is not alive to use them.

## 2026-08-30 (later) — CORRECTION + FIX: it *is* the phase change, and a watchdog solves it

**The section above named the wrong cause. Read this one instead.**

### What tracing showed
Per-tick `top`/`pre-sleep`/`post-sleep` markers were added to the loop. The last line ever logged
is `trace tick=47 pre-sleep` with **no matching `post-sleep`**, and the tick never advances again —
still 47 two minutes later. So the loop body completes fine and **`sleep(1)` never returns**. ER2
implements sleep as a Unity coroutine (`PauseForSeconds` → `pauseWithCallback` → `Coroutine_Resume`),
and the Lua coroutine is simply abandoned mid-sleep.

### Why "objective capture" was the wrong conclusion
Deploying the script as every `phase_<n>.lua` made the engine say what was really happening:

```
Lua error at 'phase_1.lua': Object reference not set to an instance of an object.
  BattleManager:TryExecutingPhaseScript() / OnPhaseChange(Int32) / NextPhase()
```

`NextPhase()` **is** being called — the phase advances shortly after a capture, and
`OnPhaseChange` tears the old phase's coroutine down. The earlier "the phase never advanced"
inference came from seeing only one `initial brain sweep`, but that only shows the NEW phase's
script failed to load; it is not evidence that no phase change occurred. Capture was a correlate,
not the cause.

### Installing the script for later phases is NOT the fix — it was reverted
It does not revive anything (the phase change is what kills the old coroutine), and it *introduces*
the NRE above: runs before that change had zero exceptions of any kind. `er2_deploy` is back to
`phase_0.lua` only, with `phases` as an opt-in for missions that genuinely want it.

### The fix that works: a watchdog on `soldier_died`
`soldier_died` is registered on the engine, not on the loop's coroutine, so it keeps firing for the
whole battle — and it already did an area scan for the kill feed, so bounded work there is proven
safe on this build. The loop body is now a named `loopBody()` that both the loop and the callback
can run. When the loop has been silent for `LOOP_STALE` (6 s), the callback drives `loopBody`
itself, no more often than `PUMP_GAP` (4 s). While the loop is alive the watchdog costs one
comparison.

**Verified live on Donchery:** loop froze at `trace tick=51 pre-sleep` as always, the watchdog
logged its one-time takeover line, and objective-attraction output *kept growing* (13 → 16 lines)
while the tick stayed frozen — with **zero Lua or engine errors**. Objective attraction, the
bail-out queue drain and the fire-mission consumer all survive the phase change now.

## 2026-08-31 — do NOT restart Steam to clear a stuck launch **[V]**

**Symptom chain, in the order it happened:** `er2_launch {"via_steam": true}` timed out after a
game was killed with SIGTERM (Steam still believed it was running). Restarting Steam to clear that
made things strictly worse, and three restarts later Steam would not launch the game at all —
`steam://rungameid/<appid>` spawned **nothing**: no harness, no reaper, no game process.

**How to tell it is Steam and not the harness:** launch in direct mode.

```
er2_launch {"via_steam": false}
```

If direct mode comes up (it did, immediately), the harness, the socket path and the game install
are all fine and the fault is entirely on the Steam side. That one call saves a long detour.

**The tell that confirmed it:** direct mode reached the menu and the GAME itself displayed

```
Steam not detected.
Make sure Steam up to date, running and logged in.
```

So Steam was running as a process but not usable by a game — up, but not logged in or blocked on a
dialog. Neither is visible from here, because Steam's own window is not inside the harness.

**Rules learned:**
- A restarted-by-script Steam is not equivalent to the one the desktop session started. Prefer
  waiting for Steam to settle over restarting it, and never restart it more than once.
- `steam -shutdown` leaves `steamwebhelper` processes behind; a "clean" restart must clear those
  too or the new instance comes up degraded.
- After any Steam restart, re-verify the LaunchOptions before blaming them. Steam rewrites
  `localconfig.vdf` on exit, so a restart can silently revert them — in this case it did not (the
  harness wrapper was still present), which is exactly why it was worth checking rather than
  assuming.
- If the game must be driven and Steam is uncooperative, non-DLC maps still work in direct mode.
  Probes that only need *some* soldiers (API identity, handle stability) do not need Donchery.

## 2026-08-31 — full-entity telemetry, and a spacing figure that was an artifact **[V]**

`getAllVehicles` exists alongside `getAllSoldiers`, so the entire battle can be enumerated rather
than sampled by radius. `TELEMETRY = true` in the phase script dumps every soldier (position, side,
suppressed, down) and every vehicle (position, name) every 2 s; `tools/battle_map.py` renders it
into a scrubbable plot. Measured on Donchery: **93 frames, 865 s, 391 peak entities, 99 vehicles**
named — including emplaced weapons (`Hotchkiss Ground Tripod`, `Bofors 40mm L/60`) and aircraft
(12 `Junkers Ju-87 'Stuka' B-2`, 6 `Messerschmitt Bf-109E3`).

**Pack the output.** `log()` costs ~1.1 KB plus a stack walk, so one call per soldier is ~350 calls
a frame and would distort what it measures. 40 entities per line makes a frame ~12 calls.

### What the movement data says
| | invaders | defenders |
|---|---:|---:|
| centroid net movement | **513 m** | 159 m |
| median path / net per man | 567 m / 362 m | 122 m / 64 m |
| never moved (<5 m total) | **0 %** | 11 % |

Invaders advance and *not one* froze across the whole battle. The 11 % of motionless defenders is
correct: the mod deliberately issues defenders no move orders at all, because measurement proved
they ignore them.

### The trap — suspect the measurement first
Nearest-neighbour spacing came out at **1.0 m median** for invaders, which reads as severe
clumping and would be a real defect. It is not. **Mounted soldiers all report their vehicle's
position**, so a truckload of nine men looks like nine men standing on one spot. Excluding anyone
within 4 m of a vehicle:

- invaders, dismounted: **32.6 m** median spacing — well dispersed, no clumping
- defenders, dismounted: **1.4 m** (p90 6.7 m) — genuinely packed

And the defender figure still is not a mod finding, because the mod never moves defenders: that is
the scenario's spawn placement plus base AI. Always filter mounted troops out of any spacing,
density or formation statistic, or every result is dominated by vehicle occupants.

Caveat kept honest: only 3 frames had enough dismounted invaders far from vehicles for the 32.6 m
figure, so treat it as indicative rather than settled.

## 2026-09-01 — the movement metrics are NOISY, and I was reading single runs **[V]**

Two battles of the **same** configuration, compared with `movement_audit.py a.log b.log`:

```
metric            run A       run B     spread   verdict
ratio              1.45        1.21       0.23    noisy
across_m           9.02        9.56       0.54   stable
along_m           15.55       13.07       2.49    noisy
roadmarch_mps      0.14        0.87       0.73    noisy
advarmour_mps      0.00        0.32       0.32    noisy
inv_frozen_pct     0.00        0.00       0.00   stable
```

**Nothing smaller than the spread column is evidence.** Two conclusions drawn earlier from single
runs both dissolve against this:

- a formation change that moved the along/across ratio 1.19 -> 1.45 looked like an improvement.
  The metric's own spread is 0.23. It proved nothing.
- the same run's `ROAD-MARCH` speed falling 0.30 -> 0.14 looked like a regression. The spread is
  0.73. That proved nothing either.

**What survives.** `inv_frozen_pct` is 0.00 in both runs with zero spread: no attacker ever freezes.
That is the metric to trust, and it is the one that matters most.

**And the one earlier conclusion that still stands, for a different reason.** Follow-the-leader was
rejected because SIX move-decisions sat at exactly 0.00 m/s with it in and every one cleared without
it. No individual delta there beats the noise - the evidence is the JOINT pattern. Six independent
metrics pinned to exactly zero simultaneously, then all releasing together, is not something
run-to-run variance produces.

**Rule going forward:** characterise the variance band before claiming any behavioural change.
`movement_audit.py <logA> <logB> ...` prints it. A single battle can show a mechanism is broken
(everything at zero) but cannot show a tuning change helped.
