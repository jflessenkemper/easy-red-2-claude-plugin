---
description: Record a video clip of the running game plus an agent-readable contact sheet. Optionally trigger the capture on a log line so the clip starts on the event rather than a guess.
allowed-tools: Bash, Read
---

Record: $ARGUMENTS

Use `${CLAUDE_PLUGIN_ROOT}/tools/record.py`. It writes an mp4 to watch **and** a labelled contact
sheet — the sheet is what YOU read, because a model can look at one tiled image but cannot watch
a video.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/tools/record.py" clip --seconds 20 --fps 6 --name <name> \
  --region 560,300,800,450
```

Two things decide whether this is worth anything:

- **Frame rate is bought with pixels.** Capture cost is proportional to AREA: a full 1920x1080
  frame takes ~660 ms (1.5 fps), a 640x360 region ~69 ms (14 fps). Always pass `--region` unless
  you genuinely need the whole screen. Region capture is PNG — the harness rejects other suffixes.
- **Check the camera is framing something BEFORE you spend the window.** Take one screenshot and
  look at it. Two 45-second recordings were wasted on bare ground because nobody checked first.

To start on an event instead of a guess, add `--wait-log "round .* over"`. Waiting on the log is
how you catch a reset or a casualty; a fixed sleep has repeatedly caught the wrong moment.

Afterwards, READ the contact sheet and report what is visibly happening. A clip shows motion, not
a decision label — never claim it shows a named branch; that comes from the log.
