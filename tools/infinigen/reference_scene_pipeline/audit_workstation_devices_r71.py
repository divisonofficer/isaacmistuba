import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba');src=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r71.blend';bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();rows=[];errors=[]
for parent in bpy.data.objects:
 if parent.type!='MESH' or 'DeskBenchFactory' not in parent.name:continue
 tree=BVHTree.FromPolygons([v.co.copy() for v in parent.data.vertices],[tuple(p.vertices) for p in parent.data.polygons]);children=[o for o in bpy.data.objects if o.parent==parent];ks=[o for o in children if o.name.startswith('Keyboard_')];ms=[o for o in children if o.name.startswith('Mouse_') and not o.name.startswith('MouseWheel')];ds=[o for o in children if o.name.startswith('Display_')];assert len(ks)==len(ms)==len(ds)==4
 for o in ks+ms:
  vs=[o.matrix_basis@v.co for v in o.data.vertices];bottom=min(v.z for v in vs);xs=[min(v.x for v in vs),max(v.x for v in vs)];ys=[min(v.y for v in vs),max(v.y for v in vs)];cx=sum(xs)/2;cy=sum(ys)/2;hit,n,i,dist=tree.ray_cast(Vector((cx,cy,bottom+.002)),Vector((0,0,-1)),.01);gap=bottom-hit.z if hit else None;inside=(.13<min(abs(x) for x in xs) and max(abs(x) for x in xs)<.83 and ys[0]>-1.195 and ys[1]<1.195);ok=hit is not None and abs(hit.z-.75)<1e-5 and gap>=-.0001 and gap<.0011 and inside;row={'device':o.name,'parent':parent.name,'support_gap_m':gap,'actual_table_hit_z':hit.z if hit else None,'footprint_inside_native_top':inside,'pass':ok};rows.append(row)
  if not ok:errors.append(row)
assert len(rows)==48;d={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'records':rows,'errors':errors,'scope':'All24 keyboard and24mouse raw meshes actual table centre ray/support gap andXY footprint. Monitor base centres atnative stand; no exhaustive scene collision/navigation or photorealism claim.','photorealism_accepted':False};p=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/workstation_device_audit_r71.json';p.write_text(json.dumps(d,indent=2));print(json.dumps({'devices':len(rows),'errors':errors}),flush=True);assert not errors
