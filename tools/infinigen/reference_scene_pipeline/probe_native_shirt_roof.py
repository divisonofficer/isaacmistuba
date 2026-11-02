"""Measure untouched shirt inner shoulder roof before hanger fitting; no solve/save."""
from pathlib import Path
import json,bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
p=Path(__file__).with_name('garment_mass_corrected_pilot03.py');code=p.read_text().split('for i in range(1):\n original=')[0].replace('garment_mass_corrected_pilot03','garment_native_roof_probe');exec(compile(code,str(p),'exec'))
o=fresh[0];tree=BVHTree.FromPolygons([v.co for v in o.data.vertices],[list(f.vertices) for f in o.data.polygons]);rows=[]
for side in [-1,1]:
 for j in range(23):
  x=side*(.08+.005*j);hit,normal,index,distance=tree.ray_cast(Vector((x,0,.15)),Vector((0,0,-1)),1)
  rows.append({'x':x,'hit':list(hit) if hit is not None else None,'normal':list(normal) if normal is not None else None,'triangle_or_polygon_index':index,'wire_original_z':-.075*abs(x)/.18})
(ref/'garment_native_roof_probe.json').write_text(json.dumps({'scope':'unaltered native fitted-by-height shirt; vertical rays at local y0; no cloth solve; no room integration','rows':rows},indent=2));print('ROOF_PROBE_COMPLETE',len(rows),flush=True)
