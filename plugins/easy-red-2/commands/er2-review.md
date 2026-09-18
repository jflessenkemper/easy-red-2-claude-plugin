---
description: Review the AI's behaviour by record-and-scrub instead of by staring at a test map — capture a real battle's telemetry and render it as an interactive plot you can play, scrub and colour by decision.
allowed-tools: Bash, Read
---

Review: $ARGUMENTS

## Why this and not a test map

This is the documented industry approach, and it is not the same thing as a demonstration range.

David Young (Treyarch), *Debugging AI with Instant In-Game Scrubbing*, **Game AI Pro 3** Ch. 6:

> "the ability to debug directly in production levels without the need to reproduce the issue in a
> test map once seen by the user is an incredibly powerful tool that saves countless man hours"

and on why a log is not enough:

> "No logging of debug information or text output can even begin to compare with" frame-accurate
> backward/forward scrubbing.

He is careful that "the use of a recorder is not a panacea" — it complements a chamber suite, it does
not replace one. The split in the literature is by **who the oracle is**: where the oracle is a
machine assertion, studios isolate (Skarupke's fixture chambers; Creative Assembly's barrier-partitioned
arenas). Where the oracle is a human judging whether the battle *looks right*, studios watch real
composite battles (Guerrilla's 8v8 playtests on a shipping map; Valve's four-bot L4D stress runs).
**Reviewing whether the AI looks intelligent is the second kind.** So run this on a REAL mission,
not the range.

## The tools already exist

- `RealisticEvents.lua` emits 9 fields per soldier every 2 s:
  `[TELEM] <t> S <uid>,<x>,<y>,<z>,<flag>,<squad>,<inVeh>,<dec>,<ri>` — position, faction,
  suppressed/down, squad, **the decision code**, and roster index.
- `tools/battle_map.py` renders those frames into one self-contained HTML: play/pause, a time
  slider, movement trails, and colour by **decision**, side, or height.

`TELEMETRY` ships `false` and `check.sh` refuses to ship it `true` — it is a diagnostic. So a review
run means deploying a telemetry build, playing, then restoring.

## Procedure

1. **Check it is safe to touch the game at all**:
   ```bash
   python3 -c "import sys;sys.path.insert(0,'${CLAUDE_PLUGIN_ROOT}/tools');import virtual_pad as v;print(v.foreign_steam_games())"
   ```
   Non-empty means the user is playing something — stop.

2. **Enable telemetry on the mission you want to review** (the mod repo's deployed copy), then
   launch and play a real battle. Prefer Stonne/Donchery over the range: a production level is the
   point.

3. **Render the plot**:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/../../tools/battle_map.py" ~/.config/unity3d/Corvostudio/"Easy Red 2"/Player.log -o /tmp/er2_mcp/battle.html
   ```
   Or via the MCP tool `er2_map`.

4. **RESTORE the shipping build** and verify `TELEMETRY = false` by grep on the DEPLOYED files, not
   the repo. The Stop guard will refuse to end the session otherwise.

5. **Hand the HTML to the user.** They scrub it; you do not need to see it to be useful. If you want
   to read it yourself, screenshot the rendered page — a model cannot scrub a slider.

## What to look for, and what not to claim

Colour by **decision** and watch for the shapes a count cannot show:

- a squad strung out in file along a road, vs bunched in a clump
- a section line-abreast behind a hull, vs walking past it
- one man standing in the open while everyone else went to ground
- men converging on a casualty, vs ignoring him
- a bound where half move while half hold, vs everyone moving at once

**Cost per frame is 2 s of game time, so this is a shape instrument, not a timing one.** Do not read
a 2 s sample as evidence about an 8 s alternation. And per this project's standing rule: a decision
label in the log is not proof of behaviour — the plot shows you where men actually were, which is
the corroboration a label lacks.
