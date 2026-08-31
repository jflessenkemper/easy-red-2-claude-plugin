#!/usr/bin/env python3
"""Render Easy Red 2 battle telemetry into an interactive map you can scrub through.

Reads the [TELEM] lines the Realistic mod's phase script emits when TELEMETRY = true, and writes a
single self-contained HTML file: every soldier and every vehicle, positioned, playable as an
animation with a time slider.

Why this exists: decision counts tell you a branch fired, not whether the battle LOOKS right. A
label cannot show you a squad strung out in file along a road, or a section bunching up behind a
halftrack, or one man left standing in the open while everyone else went to ground. This can.

Input format (see RealisticEvents.lua):
    [TELEM] <t> S <uid>,<x>,<z>,<flag>;<uid>,<x>,<z>,<flag>;...
    [TELEM] <t> V <uid>,<x>,<z>,<name>;...
  flag  I invader · D defender · i invader suppressed · d defender suppressed · x down

Usage:
    python3 battle_map.py [Player.log] [-o out.html]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import OrderedDict

TELEM = re.compile(r'\[TELEM\]\s+([\d.]+)\s+([SV])\s+(.*)$')


def parse(path):
    """-> (frames, vehicle_names). frames is an ordered {t: {"s": [...], "v": [...]}}."""
    frames = OrderedDict()
    vnames = {}
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            m = TELEM.search(line)
            if not m:
                continue
            t, kind, payload = float(m.group(1)), m.group(2), m.group(3).strip()
            fr = frames.setdefault(t, {"s": [], "v": []})
            for ent in payload.split(";"):
                if not ent:
                    continue
                parts = ent.split(",")
                if len(parts) < 4:
                    continue
                try:
                    uid, x, z = int(parts[0]), int(parts[1]), int(parts[2])
                except ValueError:
                    continue
                tag = ",".join(parts[3:])
                if kind == "S":
                    fr["s"].append([uid, x, z, tag[:1]])
                else:
                    vnames[uid] = tag
                    fr["v"].append([uid, x, z])
    return frames, vnames


def bounds(frames):
    xs, zs = [], []
    for fr in frames.values():
        for e in fr["s"]:
            xs.append(e[1]); zs.append(e[2])
        for e in fr["v"]:
            xs.append(e[1]); zs.append(e[2])
    if not xs:
        return None
    pad = 40
    return min(xs) - pad, max(xs) + pad, min(zs) - pad, max(zs) + pad


HTML = """<title>Crossing at Donchery — battle plot</title>
<style>
  /* Palette: the 1940 staff plotting map. Chinagraph blue and red are the period convention for
     own/enemy, so faction colour is SEMANTIC here and brass carries the instrument chrome -
     the accent never competes with the data it frames. Neutrals are ochre-biased, not pure grey. */
  :root {
    --ground:#10161c; --panel:#161e26; --rule:#2b3641;
    --ink:#e6e2d6; --ink-2:#9aa0a0; --label:#8a8578;
    --inv:#5b9dd9; --def:#c4443a; --armour:#c9a227;
    --down:#5d6266; --grid:rgba(201,162,39,.075);
    --f-sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    --f-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }
  @media (prefers-color-scheme: light) {
    :root {
      --ground:#e9e1ce; --panel:#f2ecdd; --rule:#c9bfa4;
      --ink:#20201c; --ink-2:#55544c; --label:#6f6a58;
      --inv:#2f6fa8; --def:#a3302a; --armour:#8a6d12;
      --down:#8d8877; --grid:rgba(90,75,25,.10);
    }
  }
  :root[data-theme="dark"] {
    --ground:#10161c; --panel:#161e26; --rule:#2b3641;
    --ink:#e6e2d6; --ink-2:#9aa0a0; --label:#8a8578;
    --inv:#5b9dd9; --def:#c4443a; --armour:#c9a227;
    --down:#5d6266; --grid:rgba(201,162,39,.075);
  }
  :root[data-theme="light"] {
    --ground:#e9e1ce; --panel:#f2ecdd; --rule:#c9bfa4;
    --ink:#20201c; --ink-2:#55544c; --label:#6f6a58;
    --inv:#2f6fa8; --def:#a3302a; --armour:#8a6d12;
    --down:#8d8877; --grid:rgba(90,75,25,.10);
  }

  * { box-sizing:border-box; }
  body { margin:0; background:var(--ground); color:var(--ink); font-family:var(--f-sans); }
  .sheet { max-width:1320px; margin:0 auto; padding:22px 20px 30px; }

  /* Masthead: mission identity, the way a map sheet is titled. */
  .mast { display:flex; justify-content:space-between; align-items:flex-end;
          gap:18px; flex-wrap:wrap; border-bottom:1px solid var(--rule); padding-bottom:12px; }
  h1 { margin:0; font-size:20px; font-weight:600; letter-spacing:-.01em; }
  .mast .where { color:var(--ink-2); font-size:13px; margin-top:3px; }
  .sheetno { font-family:var(--f-mono); font-size:11px; color:var(--label);
             text-transform:uppercase; letter-spacing:.14em; text-align:right; }

  /* Data rail: the summary reads before the detail. */
  .rail { display:grid; grid-template-columns:repeat(auto-fit,minmax(96px,1fr));
          gap:1px; background:var(--rule); border:1px solid var(--rule);
          margin:14px 0 12px; }
  .cell { background:var(--panel); padding:9px 11px; }
  .cell .k { font-size:9.5px; text-transform:uppercase; letter-spacing:.15em;
             color:var(--label); display:block; }
  .cell .v { font-family:var(--f-mono); font-variant-numeric:tabular-nums;
             font-size:17px; margin-top:3px; display:block; }
  .cell.inv .v { color:var(--inv); } .cell.def .v { color:var(--def); }
  .cell.arm .v { color:var(--armour); } .cell.dwn .v { color:var(--down); }

  .plot { position:relative; border:1px solid var(--rule); background:var(--panel);
          overflow:hidden; }
  canvas#c { display:block; width:100%; height:auto; }

  /* Transport. The slider rides ON the strength curve, so scrubbing is informed by
     where the fighting actually was rather than being a blind scrub bar. */
  .timeline { position:relative; margin-top:12px; border:1px solid var(--rule);
              background:var(--panel); padding:0; }
  canvas#curve { display:block; width:100%; height:auto; }
  input[type=range] { position:absolute; left:0; right:0; bottom:-1px; width:100%;
                      margin:0; appearance:none; background:transparent; height:22px; }
  input[type=range]::-webkit-slider-thumb { appearance:none; width:3px; height:22px;
        background:var(--ink); border:0; cursor:ew-resize; }
  input[type=range]::-moz-range-thumb { width:3px; height:22px; background:var(--ink);
        border:0; border-radius:0; cursor:ew-resize; }
  input[type=range]:focus-visible { outline:2px solid var(--armour); outline-offset:2px; }

  .controls { display:flex; align-items:center; gap:14px; flex-wrap:wrap; margin-top:12px; }
  button { font-family:var(--f-sans); font-size:12px; text-transform:uppercase;
           letter-spacing:.12em; color:var(--ink); background:transparent;
           border:1px solid var(--rule); padding:8px 16px; cursor:pointer; }
  button:hover { border-color:var(--armour); color:var(--armour); }
  button:focus-visible { outline:2px solid var(--armour); outline-offset:2px; }
  .clock { font-family:var(--f-mono); font-variant-numeric:tabular-nums;
           font-size:13px; color:var(--ink-2); }
  label.tog { font-size:11px; text-transform:uppercase; letter-spacing:.12em;
              color:var(--label); display:flex; align-items:center; gap:7px; cursor:pointer; }
  label.tog input { accent-color:var(--armour); }

  .key { display:flex; gap:20px; flex-wrap:wrap; margin-top:14px;
         padding-top:12px; border-top:1px solid var(--rule);
         font-size:11px; color:var(--ink-2); }
  .key span { display:flex; align-items:center; gap:7px; }
  .sw { width:9px; height:9px; border-radius:50%; flex:none; }
  .sw.sq { border-radius:0; }
  .sw.ring { background:transparent; border:1.5px solid var(--inv); }
  .note { margin-top:16px; font-size:11.5px; color:var(--label); max-width:68ch; line-height:1.6; }
  @media (prefers-reduced-motion: reduce) { * { transition:none !important; } }
</style>

<div class="sheet">
  <div class="mast">
    <div>
      <h1>Crossing at Donchery</h1>
      <div class="where">Kradsch&uuml;tzen-Bataillon 2 on the Meuse &middot; 16:00, Monday 13 May 1940</div>
    </div>
    <div class="sheetno" id="sheetno"></div>
  </div>

  <div class="rail">
    <div class="cell"><span class="k">Elapsed</span><span class="v" id="d-t">&mdash;</span></div>
    <div class="cell inv"><span class="k">Invader</span><span class="v" id="d-inv">&mdash;</span></div>
    <div class="cell def"><span class="k">Defender</span><span class="v" id="d-def">&mdash;</span></div>
    <div class="cell"><span class="k">Suppressed</span><span class="v" id="d-sup">&mdash;</span></div>
    <div class="cell dwn"><span class="k">Down</span><span class="v" id="d-down">&mdash;</span></div>
    <div class="cell arm"><span class="k">Vehicles</span><span class="v" id="d-veh">&mdash;</span></div>
  </div>

  <div class="plot"><canvas id="c" width="1280" height="800"></canvas></div>

  <div class="timeline">
    <canvas id="curve" width="1280" height="72"></canvas>
    <input type="range" id="slider" min="0" value="0" aria-label="Battle time">
  </div>

  <div class="controls">
    <button id="play">Play</button>
    <span class="clock" id="clock"></span>
    <label class="tog"><input type="checkbox" id="trails"> Movement trails</label>
    <label class="tog"><input type="checkbox" id="gridon" checked> 100 m grid</label>
  </div>

  <div class="key">
    <span><i class="sw" style="background:var(--inv)"></i>Invader</span>
    <span><i class="sw" style="background:var(--def)"></i>Defender</span>
    <span><i class="sw ring"></i>Suppressed &mdash; hollow</span>
    <span><i class="sw" style="background:var(--down)"></i>Down</span>
    <span><i class="sw sq" style="background:var(--armour)"></i>Vehicle or emplaced weapon</span>
  </div>

  <p class="note" id="prov"></p>
</div>

<script>
const DATA = __DATA__;
const FR = DATA.frames, TS = DATA.times, VN = DATA.vnames, B = DATA.bounds;
const c = document.getElementById('c'), g = c.getContext('2d');
const cv = document.getElementById('curve'), gc = cv.getContext('2d');
const slider = document.getElementById('slider');
const playBtn = document.getElementById('play'), clock = document.getElementById('clock');
const trailsBox = document.getElementById('trails'), gridBox = document.getElementById('gridon');
slider.max = TS.length - 1;

const tok = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// World -> canvas, aspect preserved so the ground is never stretched.
const [x0,x1,z0,z1] = B;
const S  = Math.min(c.width/(x1-x0), c.height/(z1-z0));
const ox = (c.width  - (x1-x0)*S)/2, oz = (c.height - (z1-z0)*S)/2;
const PX = x => ox + (x-x0)*S, PZ = z => oz + (z-z0)*S;

// Per-frame tallies, computed once: the rail, the clock and the strength curve all read them.
const TALLY = FR.map(f => {
  let inv=0, def=0, sup=0, down=0;
  for (const e of f.s) { const q=e[3];
    if (q==='I') inv++; else if (q==='D') def++;
    else if (q==='i') { inv++; sup++; } else if (q==='d') { def++; sup++; } else down++; }
  return {inv, def, sup, down, veh:f.v.length};
});
const PEAK = Math.max(1, ...TALLY.map(t => Math.max(t.inv, t.def)));

document.getElementById('sheetno').textContent =
  TS.length + ' frames \\u00b7 ' + DATA.maxEnt + ' peak contacts';
document.getElementById('prov').textContent =
  'Every soldier and vehicle on the map, sampled from the running battle every ' +
  (TS.length > 1 ? (TS[1]-TS[0]).toFixed(0) : '2') + ' s and plotted at true scale. ' +
  Object.keys(VN).length + ' vehicles and emplaced weapons identified by name. ' +
  'Suppression is the engine\\u2019s own state, not inferred.';

function drawGrid(){
  if (!gridBox.checked) return;
  g.strokeStyle = tok('--grid'); g.lineWidth = 1;
  const step = 100;
  g.beginPath();
  for (let x = Math.ceil(x0/step)*step; x < x1; x += step) { g.moveTo(PX(x),0); g.lineTo(PX(x),c.height); }
  for (let z = Math.ceil(z0/step)*step; z < z1; z += step) { g.moveTo(0,PZ(z)); g.lineTo(c.width,PZ(z)); }
  g.stroke();
}

function draw(i){
  const f = FR[i], t = TALLY[i];
  g.fillStyle = tok('--panel'); g.fillRect(0,0,c.width,c.height);
  drawGrid();

  if (trailsBox.checked){
    g.strokeStyle = 'rgba(150,150,140,.30)'; g.lineWidth = 1;
    for (let j = Math.max(0,i-16); j < i; j++){
      const a = FR[j], b = FR[j+1]; if(!a||!b) continue;
      const idx = new Map(b.s.map(e=>[e[0],e]));
      g.beginPath();
      for (const e of a.s){ const n = idx.get(e[0]); if(!n) continue;
        g.moveTo(PX(e[1]),PZ(e[2])); g.lineTo(PX(n[1]),PZ(n[2])); }
      g.stroke();
    }
  }

  const ARM = tok('--armour');
  for (const v of f.v){                        // armour under infantry, so men read on top
    g.fillStyle = ARM; g.fillRect(PX(v[1])-3.5, PZ(v[2])-3.5, 7, 7);
  }
  const INV = tok('--inv'), DEF = tok('--def'), DWN = tok('--down');
  for (const e of f.s){
    const q = e[3], x = PX(e[1]), y = PZ(e[2]);
    let col = DWN, hollow = false;
    if (q==='I') col = INV;
    else if (q==='D') col = DEF;
    else if (q==='i'){ col = INV; hollow = true; }
    else if (q==='d'){ col = DEF; hollow = true; }
    g.beginPath(); g.arc(x,y,2.8,0,6.2832);
    if (hollow){ g.strokeStyle = col; g.lineWidth = 1.3; g.stroke(); }
    else { g.fillStyle = col; g.fill(); }
  }

  document.getElementById('d-t').textContent    = (TS[i]-TS[0]).toFixed(0) + 's';
  document.getElementById('d-inv').textContent  = t.inv;
  document.getElementById('d-def').textContent  = t.def;
  document.getElementById('d-sup').textContent  = t.sup;
  document.getElementById('d-down').textContent = t.down;
  document.getElementById('d-veh').textContent  = t.veh;
  clock.textContent = 'Frame ' + (i+1) + ' of ' + TS.length;
  drawCurve(i);
}

// Strength of both sides over the whole action, with the playhead marked.
function drawCurve(cur){
  gc.fillStyle = tok('--panel'); gc.fillRect(0,0,cv.width,cv.height);
  const n = TALLY.length, W = cv.width, H = cv.height, pad = 6;
  const px = j => (n<2?0:j*(W/(n-1)));
  const py = v => H - pad - (v/PEAK)*(H - pad*2);
  for (const [key,col] of [['def','--def'],['inv','--inv']]){
    gc.beginPath(); gc.moveTo(px(0), H);
    for (let j=0;j<n;j++) gc.lineTo(px(j), py(TALLY[j][key]));
    gc.lineTo(px(n-1), H); gc.closePath();
    gc.fillStyle = tok(col); gc.globalAlpha = .18; gc.fill(); gc.globalAlpha = 1;
    gc.beginPath();
    for (let j=0;j<n;j++){ const X=px(j), Y=py(TALLY[j][key]); j?gc.lineTo(X,Y):gc.moveTo(X,Y); }
    gc.strokeStyle = tok(col); gc.lineWidth = 1.4; gc.stroke();
  }
  gc.strokeStyle = tok('--ink'); gc.lineWidth = 1;
  gc.beginPath(); gc.moveTo(px(cur), 0); gc.lineTo(px(cur), H); gc.stroke();
}

let playing = false, timer = null;
function step(){ let i = +slider.value + 1; if (i >= TS.length) i = 0; slider.value = i; draw(i); }
playBtn.addEventListener('click', () => {
  playing = !playing;
  playBtn.textContent = playing ? 'Pause' : 'Play';
  if (playing) timer = setInterval(step, 120); else clearInterval(timer);
});
slider.addEventListener('input', () => draw(+slider.value));
trailsBox.addEventListener('change', () => draw(+slider.value));
gridBox.addEventListener('change', () => draw(+slider.value));
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => draw(+slider.value));
new MutationObserver(() => draw(+slider.value))
  .observe(document.documentElement, {attributes:true, attributeFilter:['data-theme']});
draw(0);
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", nargs="?", default=os.path.expanduser(
        "~/.config/unity3d/Corvostudio/Easy Red 2/Player.log"))
    ap.add_argument("-o", "--out", default="battle_map.html")
    a = ap.parse_args()

    frames, vnames = parse(a.log)
    if not frames:
        print("no [TELEM] lines found in %s\n"
              "Set TELEMETRY = true in RealisticEvents.lua, redeploy, and run a battle."
              % a.log, file=sys.stderr)
        return 1

    times = sorted(frames)
    ordered = [frames[t] for t in times]
    bb = bounds(frames)
    peak = max(len(f["s"]) + len(f["v"]) for f in ordered)

    payload = {
        "bounds": list(bb),
        "times": times,
        "frames": ordered,
        "vnames": {str(k): v for k, v in vnames.items()},
        "maxEnt": peak,
    }
    html = HTML.replace("__DATA__", json.dumps(payload, separators=(",", ":")))
    with open(a.out, "w") as fh:
        fh.write(html)
    span = times[-1] - times[0] if len(times) > 1 else 0
    print("%s: %d frames, %.0f s of battle, %d peak entities, %d vehicles named"
          % (a.out, len(times), span, peak, len(vnames)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
