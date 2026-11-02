"""Read-only window sightline inventory, no assumption that historical backdrop survives."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r108_draft.blend';bpy.ops.wm.open_mainfile(filepath=str(src));deps=bpy.context.evaluated_depsgraph_get();rays=[]
for unit,cx in [('101',7.0),('102',14.5)]:
 for dx in [-.6,0,.6]:
  for z in [1.4,1.9,2.3]:
   origin=Vector((cx+dx,17.1,z));direction=Vector((0,1,0));hits=[]
   for k in range(12):
    yes,pt,n,f,o,m=bpy.context.scene.ray_cast(deps,origin,direction,distance=500)
    if not yes:break
    hits.append({'object':o.name,'key':str(o.get('program_key','')),'point':list(pt),'materials':[m.name if m else None for m in getattr(o.data,'materials',[])]});origin=pt+direction*.004
   rays.append({'unit':unit,'x':cx+dx,'z':z,'hits':hits})
w=bpy.context.scene.world;world=[{'name':n.name,'type':n.type,'image':n.image.name if getattr(n,'image',None) else None,'links':[{'from':l.from_node.name,'to':l.to_node.name} for s in n.inputs for l in s.links]} for n in w.node_tree.nodes] if w and w.use_nodes else []
a={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'rays':rays,'world_nodes':world,'scope':'18 horizontal sightlines from master rooms; successive mesh hits including glazing and background cards. Not exhaustive ray visibility or exterior consistency certification.'};(d/'master113_exterior_probe.json').write_text(json.dumps(a,indent=2));print(json.dumps({'rays':len(rays),'hit_names':sorted({h['object'] for x in rays for h in x['hits']})},indent=2))
