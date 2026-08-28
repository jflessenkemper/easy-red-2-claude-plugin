---
description: Run an Easy Red 2 play-test of the Realistic soldier-AI mod end-to-end — deploy scripts, launch headless, observe behaviour, read the decision trace, and report what to fix.
---

Run a full play-test cycle of the Realistic mod. Target mission: "$ARGUMENTS" (if empty, call
`er2_missions` and ask which mission to use).

Follow this order and do not skip the gates:

1. **Deploy** — `er2_deploy(mission)`. It luajit-validates first and refuses to copy a file that
   fails syntax. If anything reports FAIL, stop and fix the Lua before continuing.
2. **Launch** — `er2_launch()`. Idempotent. Then `er2_state()` and confirm `ready=1` AND
   `inner_alive=1`. A screenshot alone is NOT proof the game is live.
3. **Drive to the mission** — `er2_screenshot()` to see where you are, then `er2_click`
   (use `reliable: true` for scene-transition buttons) / `er2_key` to navigate. Re-screenshot
   after each step; never assume a click landed.
4. **CRITICAL — verify the brain is attached.** The single most common failure is the Squad
   Spawner's **Brain** field being empty, which silently means every soldier runs base AI.
   Confirm by `er2_log(tag="realistic", lines=20)` and looking for `ONLINE #<uid>` lines.
   If there are none, the brain is not attached — say so and stop; that is an editor action.
5. **Observe** — let the battle run, then sample:
   - `er2_log(tag="realistic", shapes=true)` — which decisions are firing, and in what proportion.
     Look for branches at zero: that usually means a branch is unreachable, not that it is idle.
   - `er2_log(tag="errors")` — must be empty. `guard(once)` lines mean a wrong API name.
   - `er2_log(tag="events")` — kill feed, objective capture, `alive invaders/defenders`.
   - `er2_screenshot()` — do the soldiers *look* right (in cover, behind armour, on roads)?
6. **Tune live if needed** — `er2_lua('global.set(0.9,"realistic_aggression")')` style calls
   retune through the F3 console with no mission restart, when the brain reads that global.
7. **Report** — state what fired, what did not, any errors, and the specific next fix. Compare
   against `~/er2-realistic/.llm/api/verified-api.md`; never propose a call that contradicts it.

Rules: never store a vec3/UserData in a Lua global (fatal on this build). Keep `VERBOSE=true`
only for short runs — logging is expensive (~1.1 KB + a stack walk per line).
