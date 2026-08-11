#!/usr/bin/env python3
"""Render a capture as a self-contained interactive waveform page.

Usage:
    python3 viewer.py ~/desk.csv [out.html] [glitch_us]
    open ~/desk.html

Channel order must be D0..D6 = red, green, yellow, white, brown, blue, black.
Traces are run-length encoded before embedding, which is what keeps a
million-sample capture down to a page a browser will happily open.
"""
import json
import sys

from probe import load
from dataline import decode, deglitch, rebuild, rle

# column index, label, role, display colour
WIRES = [
    (3, "white", "UP button", "#f0f0f0"),
    (2, "yellow", "DOWN button", "#e8c84a"),
    (1, "green", "HS3 (unused)", "#5cc65c"),
    (5, "blue", "HS4 (unused)", "#5b9be8"),
    (6, "black", "data from box", "#c8a2e8"),
    (0, "red", "+5V rail", "#e06060"),
    (4, "brown", "GND", "#b08050"),
]
BLACK, WHITE, YELLOW = 6, 3, 2


def runs_of(values):
    out, at = [], 0
    for val, n in rle(values):
        out.append([at, val])
        at += n
    return out


def spans(values, sr):
    """Contiguous asserted regions, in seconds, for shading the plot."""
    out, at, start = [], 0, None
    for val, n in rle(values):
        if val and start is None:
            start = at
        elif not val and start is not None:
            if (at - start) / sr > 0.05:
                out.append([start / sr, at / sr])
            start = None
        at += n
    if start is not None:
        out.append([start / sr, at / sr])
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src.rsplit(".", 1)[0] + ".html"
    glitch_us = float(sys.argv[3]) if len(sys.argv) > 3 else 200.0

    sr, _, rows = load(src)
    if not sr:
        sys.exit("no samplerate in capture")
    min_len = max(1, int(sr * glitch_us / 1e6))

    chans = []
    for col, name, role, colour in WIRES:
        raw = [r[col] for r in rows]
        clean = rebuild(deglitch(rle(raw), min_len))
        chans.append({"name": name, "role": role, "colour": colour,
                      "runs": runs_of(clean)})

    # Decode the data line at the measured 1000 baud for byte markers.
    bit = int(round(sr / 1000.0))
    dsig = rebuild(deglitch(rle([r[BLACK] for r in rows]), max(1, min_len // 8)))
    best, marks = None, []
    for db in (7, 8, 9):
        for par in ("none", "even", "odd"):
            for st in (1, 2):
                data, bad = decode(dsig, bit, db, par, st, False)
                total = len(data) + bad
                if total >= 4:
                    rate = len(data) / total
                    if best is None or rate > best[0]:
                        best = (rate, f"{db}{par[0].upper()}{st}", data)
    if best:
        marks = [[i / sr, f"{b:02X}"] for i, b in best[2]]

    payload = {
        "samplerate": sr,
        "duration": len(rows) / sr,
        "channels": chans,
        "marks": marks,
        "framing": best[1] if best else "",
        "up": spans([r[WHITE] for r in rows], sr),
        "down": spans([r[YELLOW] for r in rows], sr),
    }

    html = TEMPLATE.replace("__DATA__", json.dumps(payload))
    open(dst, "w").write(html)
    kb = len(html) / 1024
    print(f"wrote {dst}  ({kb:,.0f} KB, {len(rows):,} samples, "
          f"{payload['duration']:.1f}s)")
    print(f"open {dst}")


TEMPLATE = r"""<!doctype html>
<meta charset="utf-8">
<title>desk bus</title>
<style>
  body { margin:0; background:#12141a; color:#d8dae0;
         font:13px ui-monospace,SFMono-Regular,Menlo,monospace; }
  header { padding:10px 14px; border-bottom:1px solid #262a34;
           display:flex; gap:18px; align-items:baseline; flex-wrap:wrap; }
  h1 { font-size:14px; margin:0; font-weight:600; letter-spacing:.02em; }
  .hint { color:#7b8194; }
  #wrap { position:relative; }
  canvas { display:block; width:100%; cursor:crosshair; }
  #read { padding:8px 14px; border-top:1px solid #262a34; color:#9aa1b4;
          min-height:18px; }
  b { color:#e8c84a; font-weight:600; }
</style>
<header>
  <h1>LOGICDATA handset bus</h1>
  <span class="hint">scroll = zoom &nbsp;·&nbsp; drag = pan &nbsp;·&nbsp;
  double-click = reset</span>
  <span class="hint" id="meta"></span>
</header>
<div id="wrap"><canvas id="c"></canvas></div>
<div id="read">&nbsp;</div>
<script>
const D = __DATA__;
const c = document.getElementById('c'), ctx = c.getContext('2d');
const ROW = 46, PAD_L = 96, PAD_T = 10;
let t0 = 0, t1 = D.duration, drag = null;

document.getElementById('meta').textContent =
  D.duration.toFixed(1) + 's @ ' + (D.samplerate/1000) + ' kHz'
  + (D.framing ? '  ·  data line decoded as ' + D.framing : '');

function resize() {
  const w = c.parentElement.clientWidth;
  const h = PAD_T*2 + ROW*D.channels.length;
  const dpr = devicePixelRatio || 1;
  c.width = w*dpr; c.height = h*dpr; c.style.height = h+'px';
  ctx.setTransform(dpr,0,0,dpr,0,0);
  draw();
}
const X = t => PAD_L + (t - t0) / (t1 - t0) * (c.clientWidth - PAD_L - 12);
const T = x => t0 + (x - PAD_L) / (c.clientWidth - PAD_L - 12) * (t1 - t0);

function draw() {
  const w = c.clientWidth, h = PAD_T*2 + ROW*D.channels.length;
  ctx.clearRect(0,0,w,h);

  for (const [a,b] of D.up)   band(a,b,'rgba(90,190,90,.13)');
  for (const [a,b] of D.down) band(a,b,'rgba(230,150,60,.13)');

  ctx.strokeStyle = '#222633'; ctx.lineWidth = 1;
  const step = niceStep((t1-t0)/8);
  ctx.fillStyle = '#5e657a'; ctx.font = '11px ui-monospace,monospace';
  for (let t = Math.ceil(t0/step)*step; t < t1; t += step) {
    const x = Math.round(X(t))+.5;
    ctx.beginPath(); ctx.moveTo(x,PAD_T); ctx.lineTo(x,h-PAD_T); ctx.stroke();
    ctx.fillText(t.toFixed(step<0.01?4:step<1?3:2)+'s', x+3, h-PAD_T+2);
  }

  D.channels.forEach((ch,i) => {
    const yTop = PAD_T + i*ROW + 8, yBot = yTop + ROW - 24;
    ctx.fillStyle = ch.colour;
    ctx.font = '12px ui-monospace,monospace';
    ctx.fillText(ch.name, 8, yBot);
    ctx.fillStyle = '#5e657a'; ctx.font = '10px ui-monospace,monospace';
    ctx.fillText(ch.role, 8, yTop+2);

    ctx.strokeStyle = ch.colour; ctx.lineWidth = 1.4;
    ctx.beginPath();
    const s0 = t0*D.samplerate, s1 = t1*D.samplerate;
    let k = lower(ch.runs, s0), started = false;
    for (; k < ch.runs.length; k++) {
      const [s,v] = ch.runs[k];
      if (s > s1) break;
      const x = X(Math.max(s,s0)/D.samplerate), y = v ? yTop : yBot;
      if (!started) { ctx.moveTo(PAD_L, y); started = true; }
      else ctx.lineTo(x, ctx.__y);
      ctx.lineTo(x, y); ctx.__y = y;
    }
    if (started) ctx.lineTo(w-12, ctx.__y);
    ctx.stroke();
  });

  if ((t1-t0) < 1.2) {
    ctx.fillStyle = '#c8a2e8'; ctx.font = '10px ui-monospace,monospace';
    const y = PAD_T + 4*ROW + 6;
    for (const [t,hex] of D.marks)
      if (t>=t0 && t<=t1) ctx.fillText(hex, X(t)+2, y);
  }
}
function band(a,b,fill){
  if (b<t0||a>t1) return;
  ctx.fillStyle = fill;
  ctx.fillRect(X(Math.max(a,t0)),PAD_T,
               X(Math.min(b,t1))-X(Math.max(a,t0)), ROW*D.channels.length);
}
function lower(runs,s){ let lo=0,hi=runs.length-1,r=0;
  while(lo<=hi){const m=(lo+hi)>>1; if(runs[m][0]<=s){r=m;lo=m+1;}else hi=m-1;}
  return r; }
function niceStep(x){ const p=Math.pow(10,Math.floor(Math.log10(x)));
  const n=x/p; return (n<2?1:n<5?2:5)*p; }

c.addEventListener('wheel', e => {
  e.preventDefault();
  const t = T(e.offsetX), f = e.deltaY > 0 ? 1.25 : 0.8;
  const span = Math.min(D.duration, Math.max(2/D.samplerate, (t1-t0)*f));
  const frac = (t - t0) / (t1 - t0);
  t0 = Math.max(0, t - span*frac); t1 = Math.min(D.duration, t0 + span);
  t0 = Math.max(0, t1 - span);
  draw();
}, {passive:false});

c.addEventListener('mousedown', e => drag = {x:e.offsetX, t0, t1});
addEventListener('mouseup', () => drag = null);
c.addEventListener('mousemove', e => {
  if (drag) {
    const d = (e.offsetX - drag.x) / (c.clientWidth-PAD_L-12) * (drag.t1-drag.t0);
    const span = drag.t1 - drag.t0;
    t0 = Math.min(Math.max(0, drag.t0 - d), D.duration - span);
    t1 = t0 + span; draw();
  }
  const t = T(e.offsetX);
  let s = 't = ' + t.toFixed(4) + 's';
  const idx = Math.round(t*D.samplerate);
  for (const ch of D.channels) {
    const k = lower(ch.runs, idx);
    s += '   ' + ch.name + '=' + (ch.runs[k] ? ch.runs[k][1] : '?');
  }
  document.getElementById('read').innerHTML = s;
});
c.addEventListener('dblclick', () => { t0=0; t1=D.duration; draw(); });
addEventListener('resize', resize);
resize();
</script>
"""


if __name__ == "__main__":
    main()
