import bpy,bmesh,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba');src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r61.blend';bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();records=[];errors=[]
for parent in bpy.data.objects:
 if parent.type!='MESH' or 'ShowerEnclosureFactory' not in parent.name or not str(parent.get('program_key','')).endswith('_shower'):continue
 children=[o for o in bpy.data.objects if o.parent==parent and o.type=='MESH'];trays=[o for o in children if o.name.startswith('RecessedTray_')];assert len(trays)==1;tray=trays[0];bm=bmesh.new();bm.from_mesh(tray.data);bad=sum(not e.is_manifold for e in bm.edges);bm.free();verts=[];polys=[]
 for o in children:
  ev=o.evaluated_get(deps);me=ev.to_mesh();start=len(verts);verts.extend([o.matrix_world@v.co for v in me.vertices]);polys.extend([tuple(start+i for i in p.vertices) for p in me.polygons]);ev.to_mesh_clear()
 tree=BVHTree.FromPolygons(verts,polys);origin=parent.matrix_world@Vector((.0032,0,.15));direction=(parent.matrix_world.to_3x3()@Vector((0,0,-1))).normalized();hit,normal,index,distance=tree.ray_cast(origin,direction,.2);assert hit is not None;local=parent.matrix_world.inverted()@hit;bars=[o for o in children if o.name.startswith('DrainBar_')];ok=bad==0 and len(bars)==13 and abs(local.z-.015)<.0001
 record={'shower':parent.name,'tray_nonmanifold_edges':bad,'grate_bars':len(bars),'slot_ray_local_hit_z_m':local.z,'expected_well_top_m':.015,'pass':ok};records.append(record)
 if not ok:errors.append(record)
assert len(records)==8;d={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'records':records,'errors':errors,'scope':'All eight raw tray meshes closed,13 actual grate bars each,one slot ray per fixture reaches recessed well below grate. Does not prove full plumbing, drainage simulation, room collision or photographic realism.','photorealism_accepted':False};p=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/shower_drain_audit_r61.json';p.write_text(json.dumps(d,indent=2));print(json.dumps({'showers':len(records),'errors':errors}),flush=True);assert not errors
