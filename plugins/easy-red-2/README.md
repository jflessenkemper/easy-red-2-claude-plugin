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

Plus a skill: **`/easy-red-2:playtest <mission>`** — runs the whole deploy → launch → observe →
report cycle in the right order, with the gates enforced.

## Architecture

```
Claude  ──stdio JSON-RPC──>  tools/er2_mcp/server.py
                                  │
                    ┌─────────────┴──────────────┐
                    │                            │
          AF_UNIX control socket          filesystem
          /tmp/ER2Harness.sock            Player.log (telemetry out)
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
  -W 1920 -H 1080 -w 1920 -h 1080 -r 30 --framerate-limit 30 \
  --backend headless --xwayland-count 1 --harness-socket /tmp/ER2Harness.sock \
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
