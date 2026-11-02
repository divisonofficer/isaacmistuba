"""Compare actual first-hit component in bowl cavity; not a full collision certificate."""
import bpy,json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';rows=[];cx,cy=json.loads((d/'wc109_trap_inlet.json').read_text())['center_xy_m']
for folder in ['wc109_trap_pilot_v8','wc117_support_clearance_trial']:
 p=d/folder;n=json.loads((p/'build.json').read_text())['isolated_bowl_topology']['faces'];bpy.ops.wm.open_mainfile(filepath=str(p/'candidate.blend'));o=bpy.data.objects['NativeFullTankWC100'];t=BVHTree.FromPolygons([v.co.copy() for v in o.data.vertices],[tuple(f.vertices) for f in o.data.polygons],all_triangles=False);hits=[]
 for ix in range(-10,11):
  for iy in range(-10,11):
   x=ix*.006;y=iy*.004
   if (x/.06)**2+(y/.04)**2>1:continue
   loc,normal,idx,dist=t.ray_cast(Vector((cx+x,cy+y,.30)),Vector((0,0,-1)),.32)
   if loc:hits.append({'xy':[cx+x,cy+y],'face_index':idx,'component':'bowl_and_trap' if idx<n else 'auxiliary_or_preserved','surface_z':loc.z})
 rows.append({'folder':folder,'samples_with_hits':len(hits),'auxiliary_first_hits':sum(h['component']!='bowl_and_trap' for h in hits),'samples':hits})
out={'rows':rows,'scope':'Vertical first-hit rays fromz0.30 across a60x40mm-radius ellipse. Face ordering follows isolated bowl first, then support and preserved native components. This diagnoses visible non-bowl intrusion only; not full volume self-intersection or hydraulic validation.'};(d/'wc117_support_clearance_trial/visible_inlet_component_audit.json').write_text(json.dumps(out,indent=2));print([(x['folder'],x['auxiliary_first_hits'],x['samples_with_hits']) for x in rows])
