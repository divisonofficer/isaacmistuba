import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba');ref=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r62.blend';bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();changes=json.loads((ref/'realism_refinement_r62.json').read_text())['changes'];rows=[];errors=[]
for c in changes:
 o=bpy.data.objects[c['kitchen']];inv=o.matrix_world.inverted();verts=[];polys=[];owners=[];mats=[];parts=[o]+[x for x in bpy.data.objects if x.parent==o and x.type=='MESH']
 for p in parts:
  ev=p.evaluated_get(deps);me=ev.to_mesh();offset=len(verts);verts.extend([inv@p.matrix_world@v.co for v in me.vertices])
  for face in me.polygons:polys.append(tuple(offset+i for i in face.vertices));owners.append(p.name);mats.append(me.materials[face.material_index].name if me.materials else '')
  ev.to_mesh_clear()
 tree=BVHTree.FromPolygons(verts,polys);hits=[]
 for dx,dy in [(0,.10),(.10,.10),(-.10,.10),(0,-.10)]:
  h,n,i,dist=tree.ray_cast(Vector((.32+dx,c['sink_center_y_local']+dy,.95)),Vector((0,0,-1)),.4);assert h is not None;hits.append({'xy':[.32+dx,c['sink_center_y_local']+dy],'hit_z':h.z,'object':owners[i],'material':mats[i]});
 ok=all(abs(h['hit_z']-.73)<.002 and h['object']==o.name for h in hits);row={'kitchen':o.name,'included_assembly_mesh_count':len(parts),'four_bowl_rays':hits,'pass':ok};rows.append(row)
 if not ok:errors.append(row)
d={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'records':rows,'errors':errors,'scope':'Four downward rays per sink through evaluated native kitchen plus every direct mesh child. Confirms cabinet no longer fills sampled bowl interior; not exhaustive collision, plumbing or photographic realism.','photorealism_accepted':False};(ref/'kitchen_sink_void_audit_r62.json').write_text(json.dumps(d,indent=2));print(json.dumps({'kitchens':len(rows),'errors':errors}),flush=True);assert len(rows)==2 and not errors
