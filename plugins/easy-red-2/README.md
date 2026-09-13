# easy-red-2 — a Claude Code plugin for Easy Red 2 modding

See, drive and instrument **Easy Red 2** from Claude. The game runs **headless** inside a
gamescope-fork harness, so it never opens a host window and **never touches your mouse or
keyboard**. Claude gets screenshots inline, can click/type into the game, execute Lua in the
in-game F3 console, read the mod's telemetry out of `Player.log`, and syntax-validate + deploy
brain scripts into a mission.

Built for the "Realistic" soldier-AI mod (`~/er2-realistic`), but the harness half is generic.

## Install

Test without installing:

```bash
claude --plugin-dir /var/home/jflessenkemper/er2-plugin
```

Persistent (auto-loaded on startup):

```bash
mkdir -p ~/.claude/skills/easy-red-2 && cp -r /var/home/jflessenkemper/er2-plugin/. ~/.claude/skills/easy-red-2/
```

After editing plugin files, run `/reload-plugins`.

## Tools

| Tool | What it does |
|---|---|
| `er2_launch` | Start ER2 headless in the harness (idempotent; waits for `ready=1`) |
| `er2_stop` | SIGTERM the game + compositor |
| `er2_state` | `ready` / `inner_alive` / pids — **gate every action on `inner_alive=1`** |
| `er2_screenshot` | Current frame, returned **inline as an image** |
| `er2_click` | Click at screenshot-pixel coords; `reliable:true` for menu buttons (double tap ~0.6 s) |
| `er2_key` | Key tap by name (`space`, `f3`, `p`, `escape`) or Win32 VK int |
| `er2_type` | Type a literal string into the focused field |
| `er2_lua` | Run Lua via the F3 console — **live tuning with no mission restart** |
| `er2_log` | Tail `Player.log` filtered by tag: `realistic`, `events`, `bench`, `errors`; `shapes:true` aggregates |
| `er2_deploy` | luajit-validate then copy scripts → `scripts/AI/` + `scripts/mission/phase_0.lua` |
| `er2_missions` | List mission-editor missions and which scripts are deployed |

The input tools `er2_button`, `er2_move_rel`, `er2_look` and `er2_drag` also exist. They are
correct implementations of relative pointer motion, but see **Gotchas** — ER2's Free Camera does
not respond to any of them.

## Skills, commands and agents

| | |
|---|---|
| `/easy-red-2:playtest <mission>` | deploy → launch → observe → report, with the gates enforced |
| `/easy-red-2:visual-test <claim>` | prove something on screen, and reject empty frames automatically |
| `/er2-status` | harness, Steam, leftovers — and whether it is safe to touch Steam right now |
| `/er2-record <what>` | record an mp4 **and** a contact sheet; supports `--wait-log` triggering |
| `/er2-restore` | put the machine back to normal, verifying each step |
| `playtest-runner` agent | long unattended runs, off the main conversation |

## Command-line tools

`bin/er2` goes on your PATH when the plugin is installed, and drives the same tool functions the
MCP interface uses — one implementation, no drifting second copy:

```bash
er2 --list
er2 state
er2 log --tag events --lines 40
er2 click '{"x": 813, "y": 887, "reliable": true}'
```

| Script | Purpose |
|---|---|
| `tools/record.py` | Video clip + labelled contact sheet. `--region` is the frame-rate lever: capture cost is proportional to pixel AREA (full frame ~660 ms → 1.5 fps; a 640×360 region ~69 ms → 14 fps). `--wait-log REGEX` starts on an event instead of a guess. |
| `tools/visual_probe.py` | `shot` / `look` / `orbit` / `ascend` / `crop` / `contrast`. `crop` works on a SAVED frame — the harness's own region verb grabs a fresh live one, which answers a different question when you are inspecting a past capture. **`contrast` exits 1 on a visually empty frame** — it has caught a black capture that would otherwise have been reported as success. |
| `tools/virtual_pad.py` | A uinput gamepad. Refuses to create the device while a Steam game other than ER2 is running, because a virtual pad is globally visible and would disturb it. |

## Architecture

```
Claude  ──stdio JSON-RPC──>  tools/er2_mcp/server.py
                                  │
                    ┌─────────────┴──────────────┐
                    │                            │
          AF_UNIX control socket          filesystem
          ~/.er2harness.sock             Player.log (telemetry out)
                    │                     scripts/AI/*.lua (code in)
        gamescope-fork harness (headless, 1920x1080)
                    │
             Easy Red 2 (native Linux, AppId 1324780)
```

The harness is the AoE3 fork (`~/AOE-3-DE-Harness`), which is game-agnostic. ER2 is a **native
Linux** build, so no Proton/umu chain is needed — the harness launches the executable directly
with `SteamAppId` set (Steam client must be running for Steamworks init).

Manual launch equivalent of `er2_launch`:

```bash
XDG_RUNTIME_DIR=/run/user/1000 SteamAppId=1324780 SteamGameId=1324780 \
~/AOE-3-DE-Harness/build-f44/src/AOE3DEHarness --keep-alive \
  -W 1920 -H 1080 -w 1920 -h 1080 -r 60 --framerate-limit 60 \
  --force-grab-cursor \
  --backend headless --xwayland-count 1 --harness-socket ~/.er2harness.sock \
  -- "$HOME/.local/share/Steam/steamapps/common/Easy Red 2/Easy Red 2.x86_64"
```

`--keep-alive` is **required** or the socket is torn down early.

## Gotchas

- **`inner_alive=1` is the only proof the game is live.** A perfect-looking screenshot can come
  from a dead inner process.
- **Key injection returns `OK` from the compositor even if the game ignores it.** Always confirm
  with a follow-up screenshot that on-screen state actually changed. Keys sent while the game is
  still loading assets are dropped.
- **The Brain field is the #1 silent failure.** If a Squad Spawner's `Brain` is empty, every
  soldier runs base AI and `er2_log(tag="realistic")` returns **0 lines**. That is an in-editor
  action; the plugin can detect it but not fix it.
- **Never store a vec3/soldier in a Lua global** — `global.set` accepts primitives only, and a
  UserData global aborts the brain on this build.
- Keep the brain's `VERBOSE=true` for short runs only; `log()` costs ~1.1 KB + a managed stack
  walk per line on this build.

## Config (env in `.mcp.json`)

`ER2_HARNESS_SOCK`, `ER2_HARNESS_BIN`, `ER2_GAME_DIR`, `ER2_CFG_DIR`, `ER2_MOD_SRC`, `ER2_APPID`.
