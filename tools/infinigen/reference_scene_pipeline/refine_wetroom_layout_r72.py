"""Four explicit wet-room WC/vanity rearrangements; geometry/materials retained."""
import bpy,json,math,hashlib,sys
from pathlib import Path
from mathutils import Vector
root=Path('/jarvis/project/robomituba');sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import bounds
base=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r71.blend';out=base/'scene_candidate_r72.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));mapping=json.loads((ref/'room_mapping.json').read_text());changes=[]
def raw_hash(o):return hashlib.sha256(repr([tuple(v.co) for v in o.data.vertices]).encode()).hexdigest() if o.type=='MESH' else None
for unit in [101,102]:
 for name in ['ensuite','laundry_wc']:
  room_key=f'{unit}_{name}';poly=mapping[room_key]['polygon_m'];x0=min(p[0] for p in poly);x1=max(p[0] for p in poly);y0=min(p[1] for p in poly);key=room_key+'_vanity';mains=[o for o in bpy.data.objects if o.type=='MESH' and o.get('program_key')==key and 'HomeVanityFactory' in o.name];assert len(mains)==1;main=mains[0]
  group=set(o for o in bpy.data.objects if str(o.get('program_key','')).startswith(key));group.add(main);group.update(main.children_recursive);before={o.name:o.matrix_world.copy() for o in group};hashes={o.name:raw_hash(o) for o in group};old=main.matrix_world.copy()
  main.rotation_euler.z=math.pi/2;bpy.context.view_layer.update();lo,hi=bounds(main);center_x=x0+.65 if unit==101 else x1-.65;main.location.x+=center_x-(lo.x+hi.x)/2;main.location.y+=y0+.15-lo.y;bpy.context.view_layer.update();delta=main.matrix_world@old.inverted()
  for o in group:
   if o!=main and o.parent not in group:o.matrix_world=delta@before[o.name]
  bpy.context.view_layer.update()
  for o in group:
   expected=delta@before[o.name];assert max(abs(o.matrix_world[i][j]-expected[i][j]) for i in range(4) for j in range(4))<3e-5,(o.name,'assembly transform mismatch');assert raw_hash(o)==hashes[o.name]
  changes.append({'role':key,'parts':[o.name for o in group],'matrix_before':[list(x) for x in old],'matrix_after':[list(x) for x in main.matrix_world],'raw_geometry_unchanged':True,'change':'Rigid assembly move tobottom wall facing+Y; associated role parts/children follow exactly.'})
  wc=[o for o in bpy.data.objects if o.type=='MESH' and o.get('program_key')==room_key+'_wc'];assert len(wc)==1;o=wc[0];old=o.matrix_world.copy();before_hash=raw_hash(o);o.rotation_euler.z=0 if unit==101 else math.pi;bpy.context.view_layer.update();lo,hi=bounds(o);o.location.x+=(x0+.12-lo.x) if unit==101 else (x1-.12-hi.x);o.location.y+=y0+1.32-(lo.y+hi.y)/2;bpy.context.view_layer.update();assert raw_hash(o)==before_hash;changes.append({'role':o['program_key'],'matrix_before':[list(x) for x in old],'matrix_after':[list(x) for x in o.matrix_world],'bounds_after':[list(x) for x in bounds(o)],'change':'Back atouter sidewall,front towardroom,away from entry andvanity front-clearance region. Seat scale unchanged.'})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r72.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'candidate_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'changes':changes,'scope':'Four ensuite/laundry_wc WCs andfour complete vanity assemblies rigidly moved. Shower assemblies,raw meshes/materials/seat heights/lights/cameras unchanged. Both small bathroom1 layouts remain unresolved.','photorealism_accepted':False,'requires':'Saved6 preflights,all8 diagnostic,controlled four-view comparison andfresh independent review before adoption.'},indent=2));print('Saved candidate72 four WC andfour vanity moves',flush=True)
