"""Live map server for cogony. Auto-regenerates on each request.

Usage: uv run python scripts/map_server.py
Then open http://localhost:8765 in a browser.
"""

import json
import http.server
import socketserver

PORT = 8765

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>COGONY Live Map</title>
<style>
body { margin: 0; background: #0a0f1a; overflow: hidden; font-family: 'Courier New', monospace; }
#info {
  position: fixed; top: 10px; left: 10px; z-index: 10;
  background: rgba(10,15,26,0.92); color: #8899aa; padding: 10px 16px;
  border-radius: 8px; font-size: 12px; border: 1px solid #1a2744;
}
#info h2 { margin: 0 0 4px 0; color: #00e5ff; font-size: 14px; letter-spacing: 2px; }
#legend {
  position: fixed; top: 10px; right: 10px; z-index: 10;
  background: rgba(10,15,26,0.92); color: #8899aa; padding: 10px 16px;
  border-radius: 8px; font-size: 11px; border: 1px solid #1a2744;
  max-height: 80vh; overflow-y: auto;
}
#legend h3 { margin: 0 0 6px 0; color: #00e5ff; font-size: 12px; }
.lr { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
.ls { width: 12px; height: 12px; border-radius: 2px; flex-shrink: 0; }
#hover {
  position: fixed; bottom: 10px; left: 10px; z-index: 10;
  background: rgba(10,15,26,0.95); color: #e0e8f0; padding: 8px 14px;
  border-radius: 8px; font-size: 12px; border: 1px solid #1a2744;
}
#reload-btn {
  position: fixed; bottom: 10px; right: 10px; z-index: 10;
  background: #00e5ff; color: #0a0f1a; border: none; padding: 8px 16px;
  border-radius: 6px; font-size: 12px; cursor: pointer; font-weight: bold;
}
#reload-btn:hover { background: #33eeff; }
canvas { display: block; cursor: grab; }
canvas:active { cursor: grabbing; }
</style>
</head>
<body>
<div id="info"><h2>COGONY MAP</h2><div id="stats">loading...</div></div>
<div id="legend"><h3>LEGEND</h3><div id="leg"></div></div>
<div id="hover">&nbsp;</div>
<button id="reload-btn" onclick="loadMap()">⟳ RELOAD MAP</button>
<canvas id="c"></canvas>
<script>
const COLORS = {
  wall:               '#2a3040',
  junction:           '#00e5ff',
  carbon_extractor:   '#777777',
  oxygen_extractor:   '#4488ff',
  germanium_extractor:'#dddddd',
  silicon_extractor:  '#ddbb33',
  agent:              '#ff4444',
  hub:                '#ffffff',
  heart_station:      '#ff2266',
  market_station:     '#ffaa00',
  core_a_station:     '#999',
  core_d_station:     '#bbb',
  os_a_station:       '#2266cc',
  os_d_station:       '#4488ee',
  gen_a_station:      '#ddd',
  gen_d_station:      '#fff',
  storage_a_station:  '#cc9900',
  storage_d_station:  '#eebb22',
  slot_station:       '#00cccc',
};
const BIG = new Set(['hub','heart_station','agent']);
const ICONS = { hub:'H', heart_station:'♥', market_station:'$', agent:'●', slot_station:'+' };

let data, grid, objMap;
let cam = { x: 0, y: 0, z: 4 };
let drag = null;
const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');

function loadMap() {
  document.getElementById('stats').textContent = 'loading...';
  fetch('/api/map').then(r => r.json()).then(d => {
    data = d;
    cam.x = d.width / 2;
    cam.y = d.height / 2;
    grid = Array.from({length: d.height}, () => Array(d.width).fill(null));
    objMap = new Map();
    for (const o of d.objects) {
      grid[o.r][o.c] = o.type;
      objMap.set(o.r * 10000 + o.c, o);
    }
    // Stats
    const counts = {};
    for (const o of d.objects) counts[o.type] = (counts[o.type]||0)+1;
    document.getElementById('stats').textContent = d.width+'×'+d.height+' · '+d.objects.length+' objects';
    // Legend
    const el = document.getElementById('leg');
    el.innerHTML = '';
    for (const [t,c] of Object.entries(counts).sort((a,b)=>b[1]-a[1])) {
      const col = COLORS[t]||'#444';
      el.innerHTML += '<div class="lr"><div class="ls" style="background:'+col+'"></div>'+t+': '+c+'</div>';
    }
    draw();
  });
}

function draw() {
  if (!data) return;
  const cw = canvas.width, ch = canvas.height;
  const W = data.width, H = data.height, z = cam.z;
  ctx.fillStyle = '#0a0f1a';
  ctx.fillRect(0, 0, cw, ch);
  const ox = cw/2 - cam.x*z, oy = ch/2 - cam.y*z;
  for (let r = 0; r < H; r++) {
    const sy = oy + r*z;
    if (sy+z < 0 || sy > ch) continue;
    for (let c = 0; c < W; c++) {
      const sx = ox + c*z;
      if (sx+z < 0 || sx > cw) continue;
      const t = grid[r][c];
      if (!t) {
        if (z > 2) { ctx.fillStyle='#111520'; ctx.fillRect(sx,sy,z-0.4,z-0.4); }
        continue;
      }
      ctx.fillStyle = COLORS[t]||'#444';
      if (BIG.has(t)) {
        const s = 3*z;
        ctx.fillRect(sx+z/2-s/2, sy+z/2-s/2, s, s);
      } else {
        ctx.fillRect(sx, sy, z-0.3, z-0.3);
      }
      if (z >= 8 && ICONS[t]) {
        ctx.fillStyle = '#000';
        ctx.font = Math.max(8,z*0.7)+'px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(ICONS[t], sx+z/2, sy+z/2+z*0.25);
      }
    }
  }
  if (z >= 12) {
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.lineWidth = 0.5;
    const r0 = Math.max(0,Math.floor(-oy/z)), r1 = Math.min(H,Math.ceil((ch-oy)/z));
    const c0 = Math.max(0,Math.floor(-ox/z)), c1 = Math.min(W,Math.ceil((cw-ox)/z));
    for (let r=r0;r<=r1;r++){const sy=oy+r*z;ctx.beginPath();ctx.moveTo(ox+c0*z,sy);ctx.lineTo(ox+c1*z,sy);ctx.stroke();}
    for (let c=c0;c<=c1;c++){const sx=ox+c*z;ctx.beginPath();ctx.moveTo(sx,oy+r0*z);ctx.lineTo(sx,oy+r1*z);ctx.stroke();}
  }
}

canvas.addEventListener('mousedown', e => {
  drag = { sx: e.clientX, sy: e.clientY, cx: cam.x, cy: cam.y };
});
canvas.addEventListener('mousemove', e => {
  if (drag) {
    cam.x = drag.cx - (e.clientX-drag.sx)/cam.z;
    cam.y = drag.cy - (e.clientY-drag.sy)/cam.z;
    draw();
  }
  if (!data) return;
  const ox = canvas.width/2-cam.x*cam.z, oy = canvas.height/2-cam.y*cam.z;
  const gc = Math.floor((e.clientX-ox)/cam.z), gr = Math.floor((e.clientY-oy)/cam.z);
  const h = document.getElementById('hover');
  if (gc>=0 && gc<data.width && gr>=0 && gr<data.height) {
    const o = objMap.get(gr*10000+gc);
    h.textContent = o ? `(${gc},${gr}) ${o.type} #${o.id}` : `(${gc},${gr})`;
  }
});
canvas.addEventListener('mouseup', () => { drag = null; });
canvas.addEventListener('wheel', e => {
  e.preventDefault();
  cam.z = Math.max(0.5, Math.min(50, cam.z * (e.deltaY>0?0.85:1.18)));
  draw();
});
window.addEventListener('resize', () => {
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  draw();
});
canvas.width = window.innerWidth;
canvas.height = window.innerHeight;

// Auto-reload every 5 seconds
setInterval(loadMap, 5000);
loadMap();
</script>
</body>
</html>"""


def get_map_json():
    import cogony  # noqa: F401
    from cogony.mission import CogonyMission
    from mettagrid.simulator.simulator import Simulator

    m = CogonyMission()
    m.max_steps = 10
    cfg = m.make_env()
    sim = Simulator()
    s = sim.new_simulation(cfg, seed=42)

    objs = s.grid_objects()
    grid_data = []
    for o in objs.values():
        grid_data.append({
            "r": o.get("r", 0),
            "c": o.get("c", 0),
            "type": o.get("type_name", ""),
            "id": o.get("id", 0),
        })
    return json.dumps({"width": s.map_width, "height": s.map_height, "objects": grid_data})


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/map":
            try:
                data = get_map_json()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data.encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML.encode())

    def log_message(self, format, *args):
        pass  # Quiet


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Map server at http://localhost:{PORT}")
        print("Auto-reloads every 5s. Press Ctrl+C to stop.")
        httpd.serve_forever()
