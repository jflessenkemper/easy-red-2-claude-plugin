# Claude Code plugin capabilities — what this plugin is not using

Researched 2026-09-09. Docs MOVED: every `docs.claude.com/en/docs/claude-code/*` URL now 301s to
`code.claude.com/docs/en/*`. URLs below are canonical.

## Corrections to our own prior claims (both verified locally)
* **13 registered MCP tools, not 14.** `er2_silence` is a helper function, not a `TOOLS` entry.
* **Tool descriptions reference `docs/ui-map.md` 3x, but that file is at the REPO root and is not
  inside `plugins/easy-red-2/`** — an installed plugin points at a file it does not ship.

## Extension points available vs used
| Point | Location | Used? |
|---|---|---|
| Skills | `skills/<name>/SKILL.md` | yes (1, `description` only) |
| MCP server | `.mcp.json` | yes (1) |
| Hooks | `hooks/hooks.json` | **NO** |
| Agents | `agents/*.md` | **NO** |
| Monitors (experimental) | `monitors/monitors.json` | **NO** |
| Workflows | `workflows/*.js` | **NO** |
| `userConfig` | `plugin.json` | **NO** |
| `bin/` (added to Bash PATH) | `bin/` | **NO** |
| LSP | `.lsp.json` | **NO** |
| Marketplace | `.claude-plugin/marketplace.json` at REPO root | **NO** |
| MCP resources / prompts | server-side | **NO** |

Component dirs go at PLUGIN ROOT; only `plugin.json` goes in `.claude-plugin/`. Manifest requires
only `name`; ours lacks `$schema`
(`https://json.schemastore.org/claude-code-plugin-manifest.json`). Substitutions available:
`${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}` (persistent per-plugin dir), `${CLAUDE_PROJECT_DIR}`.

## Hooks — 33 events, CONFIRMED
SessionStart, Setup, UserPromptSubmit, UserPromptExpansion, PreToolUse, PermissionRequest,
PermissionDenied, PostToolUse, PostToolUseFailure, PostToolBatch, Notification, MessageDisplay,
SubagentStart, SubagentStop, TaskCreated, TaskCompleted, Stop, StopFailure, TeammateIdle,
InstructionsLoaded, ConfigChange, CwdChanged, DirectoryAdded, FileChanged, WorktreeCreate,
WorktreeRemove, PreCompact, PostCompact, PreModelSwitch, PostModelSwitch, Elicitation,
ElicitationResult, SessionEnd.

Handler types: `command`, `http`, `mcp_tool`, `prompt` (LLM evaluates), `agent`.
Blocking: exit 2 (stderr = reason), or exit 0 with
`{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",
"permissionDecisionReason":"...","updatedInput":{...}}}`.
**`PreToolUse` is the only event that can MODIFY input.** Can block: PreToolUse, UserPromptSubmit,
UserPromptExpansion, Stop, SubagentStop, TeammateIdle, TaskCreated, TaskCompleted, ConfigChange,
PreModelSwitch, PostToolBatch. `PostToolUse` cannot block but its stderr reaches Claude.
Plugin MCP matcher: `mcp__plugin_easy-red-2_easy-red-2__<tool>`; `mcp_tool` handler `server` field
takes `plugin:easy-red-2:easy-red-2`. Extras: `async`, `asyncRewake` (wakes Claude on exit 2 —
good fit for long game runs), `once`, `if`, `timeout`, `statusMessage`.
Doc: https://code.claude.com/docs/en/hooks

The docs make our argument for us: an instruction in CLAUDE.md "is a request, not a guarantee. A
`PreToolUse` hook that blocks the edit is enforcement."
(https://code.claude.com/docs/en/features-overview)

## Ordered queue (from the research)
1. **`alwaysLoad: true`** in `.mcp.json` — XS. Tool search is ON by default, so all 13 tools sit
   behind a `ToolSearch` call; a play-test uses most every turn. Also: tool descriptions AND server
   instructions truncate at **2KB each** — several of ours are at risk.
   https://code.claude.com/docs/en/mcp#scale-with-mcp-tool-search
2. **Output limits** — default MCP output cap **25,000 tokens** (warn at 10,000). Set
   `_meta["anthropic/maxResultSizeChars"]` (max 500,000 chars, TEXT ONLY) on `er2_log`.
   **Image data cannot be raised per-tool** — hard constraint on `er2_screenshot`.
3. **`er2_undeploy` + a deploy ledger** under `${CLAUDE_PLUGIN_DATA}` — there is currently NO
   revert path. Prerequisite for the Stop hook below.
4. **`hooks/hooks.json`**: `PreToolUse` on Bash denying `pkill -9`/`kill -9`/`killall` against
   steam; `Stop` refusing to end with a diagnostic build deployed (pair with `SessionEnd` for
   cleanup, which cannot block); audio guard denying `@DEFAULT_SINK@` mutes.
5. **`monitors/monitors.json`** — best structural fit for "history of silent failures": each stdout
   line is delivered to Claude as a notification with NO tool call. `when` takes `"always"` or
   `"on-skill-invoke:<skill>"`. Caveats: EXPERIMENTAL, interactive sessions only, cannot read
   `${user_config.*}`, runs in session cwd.
   https://code.claude.com/docs/en/plugins-reference#monitors
6. **MCP resources** — `@easy-red-2:file://ui-map`, auto-fetched as attachments, `@`-autocompletable.
   Needs `resources/list` + `resources/read` (we have neither). Candidates: the UI map, the Lua API
   reference, mission inventory, last screenshot.
   https://code.claude.com/docs/en/mcp#use-mcp-resources
7. **`agents/playtest-runner.md`** — frontmatter: `name`, `description` (required), `tools`,
   `disallowedTools`, `model`, `effort`, `maxTurns`, `skills`, `memory` (user/project/local —
   persistent cross-session, ideal for accumulated UI coords + failure modes), `background`,
   `isolation: worktree`. **Plugin agents CANNOT use `hooks`, `mcpServers` or `permissionMode`** —
   silently dropped, so guards must live in `hooks/hooks.json`. Background subagents lose most
   non-MCP built-ins.
8. **Skill upgrade** — add `allowed-tools`; `disable-model-invocation: true` (docs explicitly
   recommend for side-effecting skills, which a play-test is); `argument-hint`; and dynamic
   context injection via `` !`command` `` to open the skill with real harness state instead of a
   guess. Keep SKILL.md <500 lines, move the UI map / failure catalogue to sibling files.
9. **`userConfig`** — replace the hardcoded socket env with a typed prompted setting
   (`${user_config.KEY}`, exported to hooks as `CLAUDE_PLUGIN_OPTION_<KEY>`). Cannot substitute
   into shell-form hook commands.
10. **marketplace.json + `claude plugin validate . --strict`** — repo is already laid out as
    `plugins/easy-red-2`, the shape a marketplace expects. Dev loop:
    `claude --plugin-dir ./plugins/easy-red-2` then `/reload-plugins`. ALWAYS bump `version` or it
    falls back to a git SHA. https://code.claude.com/docs/en/plugin-marketplaces

Also: MCP calls over **2 minutes** are auto-backgrounded, but this is DISABLED in non-interactive
mode unless `CLAUDE_AUTO_BACKGROUND_TASKS=1`. `er2_launch` and `er2_play_mission` both cross that.

## DO NOT BUILD ON THESE — unconfirmed
* **`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`** — ABSENT from the official
  Claude Code docs (zero hits in a full grep of `mcp.md`, and zero for `annotations`). Only
  documented `_meta` keys: `anthropic/maxResultSizeChars`, `anthropic/requiresUserInteraction`,
  `anthropic/alwaysLoad`. Community claims exist but are unverified. Harmless to add as standard
  MCP; **do not rely on them as a safety mechanism** — use hooks, which are documented enforcement.
* **`outputSchema` / structured content for MCP** — zero hits; documented for the Agent SDK, not
  MCP in Claude Code. Treat as unsupported.
* Exact `tools:` allowlist string for a plugin-bundled MCP server in AGENT frontmatter — not
  stated. Test empirically with `/context`.
* Whether plugin SKILL `hooks` frontmatter works — put guards in `hooks/hooks.json` and avoid it.
* MCP sampling — not documented. Roots and elicitation ARE supported.
* **No per-server tool cap exists** ("the practical limit is your context window budget"), so 13
  tools is fine; the real levers are the 2KB truncation and `alwaysLoad`.
* Monitors and themes are labelled EXPERIMENTAL by Anthropic.

Rejected on judgement: output styles (`force-for-plugin` overrides the user's own style — rude);
`settings.json` `agent` (too invasive); workflows (a game you can only run one of does not
parallelise); `anthropic/requiresUserInteraction` on `er2_deploy` (would stall unattended runs).
