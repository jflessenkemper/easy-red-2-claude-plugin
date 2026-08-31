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


HTML = """<title>Easy Red 2 — battle map</title>
<style>
  :root { --bg:#0d1117; --fg:#c9d1d9; --dim:#8b949e; --panel:#161b22; --line:#30363d; }
  @media (prefers-color-scheme: light) {
    :root { --bg:#ffffff; --fg:#1f2328; --dim:#57606a; --panel:#f6f8fa; --line:#d0d7de; }
  }
  :root[data-theme="dark"]  { --bg:#0d1117; --fg:#c9d1d9; --dim:#8b949e; --panel:#161b22; --line:#30363d; }
  :root[data-theme="light"] { --bg:#ffffff; --fg:#1f2328; --dim:#57606a; --panel:#f6f8fa; --line:#d0d7de; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.5 Inter, ui-sans-serif, system-ui, sans-serif; }
  header { padding:14px 18px 10px; }
  h1 { margin:0 0 4px; font-size:17px; font-weight:600; }
  .sub { color:var(--dim); font-size:12.5px; }
  #wrap { padding:0 18px 18px; }
  canvas { width:100%; height:auto; background:var(--panel);
           border:1px solid var(--line); border-radius:6px; display:block; }
  .bar { display:flex; gap:12px; align-items:center; margin:12px 0 8px; flex-wrap:wrap; }
  button { background:var(--panel); color:var(--fg); border:1px solid var(--line);
           border-radius:6px; padding:6px 14px; font:inherit; cursor:pointer; }
  button:hover { border-color:var(--dim); }
  input[type=range] { flex:1; min-width:220px; accent-color:#d29922; }
  .k { display:flex; gap:16px; flex-wrap:wrap; color:var(--dim); font-size:12px; margin-top:6px; }
  .k i { display:inline-block; width:9px; height:9px; border-radius:50%; margin-right:5px;
         vertical-align:middle; }
  .k s { display:inline-block; width:9px; height:9px; margin-right:5px; vertical-align:middle;
         text-decoration:none; }
  code { font-variant-numeric:tabular-nums; }
</style>
<header>
  <h1>Easy Red 2 — full battle map</h1>
  <div class="sub">Every soldier and vehicle, sampled from the running battle.
    <code id="meta"></code></div>
</header>
<div id="wrap">
  <canvas id="c" width="1200" height="820"></canvas>
  <div class="bar">
    <button id="play">▶ Play</button>
    <input type="range" id="slider" min="0" value="0">
    <code id="tlabel"></code>
    <label class="sub"><input type="checkbox" id="trails"> trails</label>
  </div>
  <div class="k">
    <span><i style="background:#58a6ff"></i>invader</span>
    <span><i style="background:#c93c37"></i>defender</span>
    <span><i style="background:#58a6ff;opacity:.35"></i>suppressed (hollow)</span>
    <span><i style="background:#6e7681"></i>down</span>
    <span><s style="background:#d29922"></s>vehicle</span>
  </div>
</div>
<script>
const DATA = __DATA__;
const B = DATA.bounds, FR = DATA.frames, TS = DATA.times, VN = DATA.vnames;
const c = document.getElementById('c'), g = c.getContext('2d');
const slider = document.getElementById('slider'), tlabel = document.getElementById('tlabel');
const playBtn = document.getElementById('play'), trailsBox = document.getElementById('trails');
slider.max = TS.length - 1;
document.getElementById('meta').textContent =
  TS.length + ' frames · ' + DATA.maxEnt + ' peak entities · ' +
  (TS.length ? (TS[TS.length-1] - TS[0]).toFixed(0) + ' s of battle' : '');

// world -> canvas, preserving aspect so the map is never stretched
const [x0,x1,z0,z1] = B;
const sx = c.width / (x1-x0), sz = c.height / (z1-z0), S = Math.min(sx,sz);
const ox = (c.width  - (x1-x0)*S)/2, oz = (c.height - (z1-z0)*S)/2;
const PX = x => ox + (x-x0)*S, PZ = z => oz + (z-z0)*S;

function css(v){ return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }

function draw(i){
  const f = FR[i];
  g.clearRect(0,0,c.width,c.height);

  if (trailsBox.checked){
    g.strokeStyle = 'rgba(120,130,140,.28)'; g.lineWidth = 1;
    for (let j = Math.max(0,i-14); j < i; j++){
      const a = FR[j], b = FR[j+1]; if(!a||!b) continue;
      const bi = new Map(b.s.map(e=>[e[0],e]));
      g.beginPath();
      for (const e of a.s){ const n = bi.get(e[0]); if(!n) continue;
        g.moveTo(PX(e[1]),PZ(e[2])); g.lineTo(PX(n[1]),PZ(n[2])); }
      g.stroke();
    }
  }

  for (const v of f.v){                       // vehicles first, so infantry draw on top
    g.fillStyle = '#d29922';
    g.fillRect(PX(v[1])-4, PZ(v[2])-4, 8, 8);
  }
  for (const e of f.s){
    const flag = e[3];
    const x = PX(e[1]), y = PZ(e[2]);
    let col = '#6e7681', hollow = false;
    if (flag === 'I'){ col = '#58a6ff'; }
    else if (flag === 'D'){ col = '#c93c37'; }
    else if (flag === 'i'){ col = '#58a6ff'; hollow = true; }
    else if (flag === 'd'){ col = '#c93c37'; hollow = true; }
    g.beginPath(); g.arc(x,y,2.9,0,6.2832);
    if (hollow){ g.strokeStyle = col; g.globalAlpha = .75; g.lineWidth = 1.2; g.stroke(); g.globalAlpha = 1; }
    else { g.fillStyle = col; g.fill(); }
  }

  let inv=0, def=0, sup=0, down=0;
  for (const e of f.s){ const q=e[3];
    if(q==='I') inv++; else if(q==='D') def++;
    else if(q==='i'){inv++;sup++;} else if(q==='d'){def++;sup++;} else down++; }
  tlabel.textContent = 't=' + TS[i].toFixed(0) + 's  ·  inv ' + inv + '  def ' + def +
                       '  ·  suppressed ' + sup + '  down ' + down + '  ·  veh ' + f.v.length;
}

let playing=false, timer=null;
function step(){ let i=+slider.value+1; if(i>=TS.length) i=0; slider.value=i; draw(i); }
playBtn.onclick = () => {
  playing = !playing; playBtn.textContent = playing ? '❚❚ Pause' : '▶ Play';
  if (playing) timer = setInterval(step, 110); else clearInterval(timer);
};
slider.oninput = () => draw(+slider.value);
trailsBox.onchange = () => draw(+slider.value);
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
