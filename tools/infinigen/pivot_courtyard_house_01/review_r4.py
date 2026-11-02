"""Cut baseboards out of portals; regenerate home kitchens with oak cabinets."""
import argparse,json,sys
from pathlib import Path
import bpy,bmesh
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner.proc_home import HomeKitchenRunFactory
import shapely

p=argparse.ArgumentParser();p.add_argument('blend');p.add_argument('--out',required=True);a=p.parse_args()
bpy.ops.wm.open_mainfile(filepath=a.blend)
doc=json.loads((ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01/floor_plan.json').read_text())
ports=[]
for kind in ('doors','opens','entrance'):
 for v in doc[kind].values():
  ports.append(eval(v['shape']).buffer(.22,cap_style=2))
portal_region=shapely.union_all(ports);n=0;removed_components=0
for o in list(bpy.data.objects):
 if o.type=='MESH' and o.name.startswith('BaseboardFactory'):
  bm=bmesh.new();bm.from_mesh(o.data);seen=set();delete=[]
  for v in bm.verts:
   if v in seen:continue
   comp=[];q=[v];seen.add(v)
   while q:
    x=q.pop();comp.append(x)
    for e in x.link_edges:
     y=e.other_vert(x)
     if y not in seen:seen.add(y);q.append(y)
   pts=[o.matrix_world@v.co for v in comp]
   box=shapely.box(min(v.x for v in pts),min(v.y for v in pts),max(v.x for v in pts),max(v.y for v in pts))
   if box.intersection(portal_region).area>1e-7:delete.extend(comp);removed_components+=1
  if delete:bmesh.ops.delete(bm,geom=delete,context='VERTS')
  bm.to_mesh(o.data);bm.free();o.data.update();n+=1
kitchens=[]
for old in list(bpy.data.objects):
 if old.type!='MESH' or 'HomeKitchenRunFactory' not in old.name:continue
 rid=old.get('ir_room');name=old.name;mat=old.matrix_world.copy()
 length=max(v.co.y for v in old.data.vertices)-min(v.co.y for v in old.data.vertices)
 fac=HomeKitchenRunFactory(44 if rid=='kitchen_0/0' else 55);fac.front='oak';fac.L=length
 new=fac.spawn_asset(804);new.matrix_world=mat;new['ir_room']=rid
 bpy.data.objects.remove(old,do_unlink=True);new.name=name;kitchens.append(rid)
bpy.context.view_layer.update()
s=bpy.context.scene;dep=bpy.context.evaluated_depsgraph_get();hits=[]
for x,y in ((12,11.5),(20.5,15.4),(16.5,9.9),(10.5,14.2)):
 h=s.ray_cast(dep,Vector((x,y,1)),Vector((0,0,-1)),distance=2)
 hits.append({'xy':[x,y],'object':h[4].name if h[0] else None,'z':h[1].z if h[0] else None})
 assert h[0] and 'BaseboardFactory' not in h[4].name,hits
s['pivot_revision']='r4_direct_review'
bpy.ops.wm.save_as_mainfile(filepath=a.out)
Path(a.out).with_suffix('.review.json').write_text(json.dumps({'baseboard_meshes_cut':n,'baseboard_components_removed':removed_components,'kitchens_regenerated':kitchens,'threshold_rays':hits},indent=2))
print('PIVOT_R4_COMPLETE',json.dumps(hits),flush=True)
