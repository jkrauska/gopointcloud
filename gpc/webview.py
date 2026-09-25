"""Tiny browser viewer for our outputs: three.js + PLYLoader, orbit controls,
camera path drawn as a red polyline. Serves out/<run>/ over http so the PLY
files load by relative URL. No Potree conversion needed at this size
(<~5M points); for bigger clouds convert to COPC and use a Potree viewer.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import viz

_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>
  html,body{{margin:0;height:100%;background:#111;color:#ddd;font:13px system-ui}}
  #hud{{position:fixed;top:8px;left:8px;background:#0008;padding:6px 10px;border-radius:6px}}
  label{{margin-right:10px}}
</style>
<script type="importmap">{{"imports":{{
  "three":"https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js",
  "three/addons/":"https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/"}}}}</script>
</head><body>
<div id="hud">
  <b>{title}</b> &nbsp;
  <label><input type="checkbox" id="dense" checked> dense</label>
  <label><input type="checkbox" id="sparse" {sparse_checked}> sparse</label>
  <label><input type="checkbox" id="cams" checked> cameras</label>
  <label>size <input type="range" id="size" min="0.01" max="0.2" step="0.01" value="0.04"></label>
  <span id="info"></span>
</div>
<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';
import {{ PLYLoader }} from 'three/addons/loaders/PLYLoader.js';
const scene = new THREE.Scene();
const renderer = new THREE.WebGLRenderer({{antialias:true}});
renderer.setSize(innerWidth, innerHeight); renderer.setPixelRatio(devicePixelRatio);
document.body.appendChild(renderer.domElement);
const camera = new THREE.PerspectiveCamera(60, innerWidth/innerHeight, 0.05, 5000);
camera.up.set(0,0,1);                       // ENU: Z is up
camera.position.set(-30, -30, 25);
const controls = new OrbitControls(camera, renderer.domElement);
scene.add(new THREE.AxesHelper(5));
const grid = new THREE.GridHelper(200, 40, 0x444444, 0x2a2a2a); grid.rotation.x = Math.PI/2; scene.add(grid);

const mats = {{}};
function addPly(url, key, size) {{
  new PLYLoader().load(url, g => {{
    const m = new THREE.PointsMaterial({{size, vertexColors: g.hasAttribute('color')}});
    mats[key] = m;
    const p = new THREE.Points(g, m); p.visible = document.getElementById(key).checked;
    scene.add(p);
    document.getElementById(key).onchange = e => p.visible = e.target.checked;
    document.getElementById('info').textContent += ` ${{key}}: ${{g.attributes.position.count.toLocaleString()}} pts`;
    if (key === '{primary}') {{
      g.computeBoundingSphere(); const bs = g.boundingSphere;
      controls.target.copy(bs.center);
      camera.position.set(bs.center.x - bs.radius, bs.center.y - bs.radius, bs.center.z + bs.radius * 0.8);
      camera.far = bs.radius * 20; camera.updateProjectionMatrix();
    }}
  }});
}}
{dense_line}
addPly('sparse_enu.ply', 'sparse', 0.15);
const cams = {cams};
if (cams.length) {{
  const pts = cams.map(c => new THREE.Vector3(...c));
  const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({{color: 0xff3333}}));
  scene.add(line);
  document.getElementById('cams').onchange = e => line.visible = e.target.checked;
}}
document.getElementById('size').oninput = e => {{ if (mats.dense) mats.dense.size = +e.target.value; }};
addEventListener('resize', () => {{ camera.aspect = innerWidth/innerHeight; camera.updateProjectionMatrix(); renderer.setSize(innerWidth, innerHeight); }});
(function loop() {{ requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); }})();
</script></body></html>
"""


def write(out_dir: Path, aligned_model: Path, title: str | None = None) -> Path:
    _, _, cams = viz.load_model(aligned_model)
    order = sorted(cams)  # frame names sort chronologically
    path = [[round(float(x), 3) for x in cams[n]] for n in order]
    has_dense = (out_dir / "dense_enu.ply").exists()
    dense = "addPly('dense_enu.ply', 'dense', 0.04);" if has_dense else ""
    html = _HTML.format(title=title or out_dir.name, cams=json.dumps(path), dense_line=dense,
                        primary="dense" if has_dense else "sparse",
                        sparse_checked="" if has_dense else "checked")
    p = out_dir / "index.html"
    p.write_text(html)
    print(f"webview: {p}  (serve with: python -m http.server -d {out_dir} 8765)")
    return p


if __name__ == "__main__":
    import sys
    write(Path(sys.argv[1]), Path(sys.argv[2]))
