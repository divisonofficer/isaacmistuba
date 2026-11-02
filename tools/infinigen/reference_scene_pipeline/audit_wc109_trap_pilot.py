"""Bounded trap wall topology/self-overlap and vertical waste-visibility audit."""
import bpy,json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';p=d/'wc109_trap_pilot';bpy.ops.wm.open_mainfile(filepath=str(p/'candidate.blend'));body=bpy.data.objects['NativeFullTankWC100'];trap=bpy.data.objects['WC109_continuous_hollow_S_trap'];inlet=json.loads((d/'wc109_trap_inlet.json').read_text());cx,cy=inlet['center_xy_m']
def tree(o):return BVHTree.FromPolygons([o.matrix_world@v.co for v in o.data.vertices],[tuple(f.vertices) for f in o.data.polygons])
t=tree(trap);bt=tree(body);faces=[set(f.vertices) for f in trap.data.polygons];bad={(min(a,b),max(a,b)) for a,b in t.overlap(t) if a!=b and not faces[a].intersection(faces[b])};assert not bad,('nonadjacent wall self-intersections',len(bad));rays=[]
for ix in range(-8,9):
 for iy in range(-5,6):
  x=cx+ix*.004;y=cy+iy*.004;o=Vector((x,y,.17));before=bt.ray_cast(o,Vector((0,0,-1)),.18)[0]
  if before is not None:continue
  after=t.ray_cast(o,Vector((0,0,-1)),.18)[0];rays.append({'xy':[x,y],'before_native_body_hit':False,'after_trap_hit_z':after.z if after is not None else None})
assert rays and all(v['after_trap_hit_z'] is not None and v['after_trap_hit_z']>0 for v in rays)
(p/'geometry_audit.json').write_text(json.dumps({'pass':True,'nonadjacent_trap_wall_surface_self_intersections':len(bad),'formerly_open_vertical_rays':len(rays),'all_now_hit_trap_wall_above_floor':True,'rays':rays,'scope':'One native prototype, axial vertical aperture samples and trap wall nonadjacent surface pairs only. No joint union/void continuity, fluid seal, original pedestal/back collision or real-room acceptance.'},indent=2));print('WC109_TRAP_BOUNDED_AUDIT_PASS',len(rays))
