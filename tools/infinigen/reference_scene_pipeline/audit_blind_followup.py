import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
root=Path('/jarvis/project/robomituba');office=sys.argv[1]=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;rev=26 if office else 32;source=root/'out/infinigen_v2'/f'kr_{scene}_{seed}/full'/f'scene_candidate_r{rev}.blend';bpy.ops.wm.open_mainfile(filepath=str(source));bpy.context.view_layer.update();rows=[];errors=[]
for o in bpy.data.objects:
 key=o.get('program_key','')
 if office and o.name.startswith('BlindR1_'):
  if '_key_' in key:
   z=min(v.co.z for v in o.data.vertices)+o.location.z
   if abs(z-.763)>.0001:errors.append(o.name+' keyboard support mismatch')
  if 'active_glass' in key:
   bs=next(n for n in o.data.materials[0].node_tree.nodes if n.type=='BSDF_PRINCIPLED');assert bs.inputs['Metallic'].default_value==0
  rows.append({'object':o.name,'role':key,'local_dimensions':list(o.dimensions)})
 if not office and key.endswith('_formed_basin'):
  bm=__import__('bmesh').new();bm.from_mesh(o.data);manifold=all(e.is_manifold for e in bm.edges);bm.free()
  minimum=min(v.co.z for v in o.data.vertices);gap=minimum-.72
  # Bottom sits 5mm into native counter, matching inherited baseline vessel installation.
  if not manifold or abs(minimum-.715)>1e-5:errors.append(o.name+' invalid shell')
  rows.append({'object':o.name,'closed_manifold_shell':manifold,'minimum_local_z':minimum,'counter_top_z':.72,'inherited_embed_m':-gap})
assert rows
p=root/'data/venue_refs/floor_plans_v3'/scene/f'blind_followup_geometry_r{rev}.json';p.write_text(json.dumps({'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'objects':rows,'errors':errors,'photorealism_accepted':False,'scope':'new component support / shell topology only; not full collision certification'},indent=2));print(json.dumps({'revision':rev,'components':len(rows),'errors':errors}));assert not errors
