# easy-red-2 — Claude Code plugin (+ marketplace)

Drive and observe **Easy Red 2** from Claude: headless game control, inline screenshots, input
injection, in-game Lua execution, log telemetry, and validated script deployment.

This repository is **both** a Claude Code plugin marketplace and the home of the plugin.

```
.claude-plugin/marketplace.json     <- marketplace manifest
plugins/easy-red-2/                 <- the plugin
  .claude-plugin/plugin.json
  .mcp.json
  skills/playtest/SKILL.md
  tools/er2_mcp/server.py
docs/ui-map.md                      <- verified in-game UI coordinates + gotchas
```

## Install

```
/plugin marketplace add ASAP-Australia/easy-red-2-claude
/plugin install easy-red-2@asap-australia
```

Local development (no marketplace needed):

```bash
claude --plugin-dir ./plugins/easy-red-2
```

Then `/reload-plugins` after edits.

## Requirements

- Linux with PipeWire (`pactl`) and Vulkan
- Easy Red 2 (Steam AppId 1324780), native Linux build
- The gamescope-fork harness binary that provides the Unix control socket
- `python3`; optional `magick` (screenshot downscaling) and `luajit` (Lua validation)

See `plugins/easy-red-2/README.md` for the full tool reference and gotchas.

## License

MIT — see `LICENSE`.
