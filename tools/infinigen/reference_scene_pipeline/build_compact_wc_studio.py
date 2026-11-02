"""Native WC concealed-cistern visual prototype. Not room integration or plumbing validation."""
import bpy,bmesh,json,hashlib,math
from pathlib import Path
from mathutils import Matrix,Vector
root=Path('/jarvis/project/robomituba');ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r72.blend';out=ref/'native_compact_wc_studio73';assert not out.exists();out.mkdir();name='Residential03_101_bathroom1_wc'
for obj in list(bpy.data.objects):bpy.data.objects.remove(obj,do_unlink=True)
with bpy.data.libraries.load(str(src),link=False) as (a,b):b.objects=[name]
wc=b.objects[0];bpy.context.collection.objects.link(wc);wc.parent=None;wc.rotation_euler=(0,0,0);wc.location=(0,0,0);bpy.context.view_layer.update();me=wc.data;adj=[set() for _ in me.vertices]
for e in me.edges:
 i,j=e.vertices;adj[i].add(j);adj[j].add(i)
remaining=set(range(len(me.vertices)));groups=[]
while remaining:
 i=next(iter(remaining));g={i};queue=[i];remaining.remove(i)
 while queue:
  for j in adj[queue.pop()]:
   if j in remaining:remaining.remove(j);g.add(j);queue.append(j)
 groups.append(g)
assert len(groups)==9
bounds=[]
for group in groups:
 vs=[me.vertices[i].co for i in group];bounds.append(([min(v[k] for v in vs) for k in range(3)],[max(v[k] for v in vs) for k in range(3)]))
# Explicit native component evidence from probe72, refused if topology differs.
assert [len(g) for g in groups]==[31064,2686,7342,14124,412,218,152,192,192]
assert bounds[5][1][2]<.3 and bounds[5][0][0]<-.4 and bounds[6][0][2]>.26
wc['audit_kind']='prototype';wc['program_key']='native_wc_studio';wc['reference_scene_owner']='prototype_only'
def align():
 bpy.context.view_layer.update();p=[wc.matrix_world@v.co for v in wc.data.vertices];wc.location.x+=.025-min(v.x for v in p);wc.location.z-=min(v.z for v in p);bpy.context.view_layer.update();p=[wc.matrix_world@v.co for v in wc.data.vertices];return {'bounds':[[min(v[k] for v in p) for k in range(3)],[max(v[k] for v in p) for k in range(3)]],'width_m':max(v.y for v in p)-min(v.y for v in p),'depth_m':max(v.x for v in p)-min(v.x for v in p),'height_m':max(v.z for v in p)-min(v.z for v in p)}
def mat(name,color,rough,metal=0):
 m=bpy.data.materials.new(name);m.use_nodes=True;b=m.node_tree.nodes['Principled BSDF'];b.inputs['Base Color'].default_value=(*color,1);b.inputs['Roughness'].default_value=rough;b.inputs['Metallic'].default_value=metal;return m
wallmat=mat('Neutral studio service wall',(.55,.56,.57),.75);floor=mat('Neutral studio floor',(.26,.27,.28),.65)
def box(name,loc,size,m,bevel=0):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=name;o.dimensions=size;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(m)
 if bevel:mod=o.modifiers.new('Manufactured edge','BEVEL');mod.width=bevel;mod.segments=3
 return o
box('Service wall thickness200mm',(-.1,0,.9),(.2,1.3,1.8),wallmat,.001);box('Floor',(.65,0,-.02),(1.7,1.5,.04),floor,.001)
scene=bpy.context.scene;scene.world=scene.world or bpy.data.worlds.new('Studio');scene.world.use_nodes=True;scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.15
for name,loc,power,size in [('key',(1,-1.2,1.9),100,1.0),('fill',(.6,1,1.4),45,.7)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((.3,0,.5))-o.location).to_track_quat('-Z','Y').to_euler()
views=[{'name':'native_wc_manufacture','location':[1.65,-1.1,1.12],'target':[.32,0,.58],'hfov':48,'render_width':960,'samples':32}];(out/'views.json').write_text(json.dumps(views,indent=2));before=align();bpy.ops.wm.save_as_mainfile(filepath=str(out/'baseline.blend'))
# Retain bowl,seat,cover andstand exact vertices. Retain rear support connectedness,
# compress only its tail behind native bowl rear; remove identified exposed tank/cap/lever.
wc.data=wc.data.copy();me=wc.data;kept={i:tuple(me.vertices[i].co) for group in groups[:4] for i in group};old_rear=bounds[4][0][0];join_x=bounds[0][0][0];new_rear=-.28;assert old_rear<new_rear<join_x
for i in groups[4]:
 v=me.vertices[i]
 if v.co.x<join_x:v.co.x=join_x+(v.co.x-join_x)*(new_rear-join_x)/(old_rear-join_x)
assert all(tuple(me.vertices[i].co)==co for i,co in kept.items())
bm=bmesh.new();bm.from_mesh(me);bm.verts.ensure_lookup_table();remove=set().union(*groups[5:]);bmesh.ops.delete(bm,geom=[bm.verts[i] for i in remove],context='VERTS');bm.to_mesh(me);bm.free();me.update();wc.name='Native concealed cistern WC visual prototype';after=align();assert abs(before['width_m']-after['width_m'])<2e-6 and after['depth_m']<.56
steel=mat('Flush plate satin steel',(.48,.51,.53),.3,1);gasket=mat('Flush plate mounting seam',(.02,.025,.03),.6)
box('Flush plate gasket',(.002,0,1.18),(.004,.224,.144),gasket,.001);box('Flush service faceplate',(.0055,0,1.18),(.003,.22,.14),steel,.001)
for name,y,width in [('large',-.04,.10),('small',.065,.07)]:box('Dual flush '+name,(.008, y,1.18),(.002,width,.075),steel,.002)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'candidate.blend'));(out/'scope.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'native_object':'Residential03_101_bathroom1_wc','before':before,'after':after,'preserved_components':['native bowl','native seat','native raised cover','native floor stand'],'preserved_original_component_vertices':sum(len(g) for g in groups[:4]),'modified_component':'Native rear support tail only, x-coordinate compression behind bowl rear','removed_components':['exposed tank','tank cap','flush lever mount','flush lever'],'seat_height_target_m':.42,'horizontal_width_preserved':True,'room_integration':False,'photorealism_accepted':False,'limitations':['Concealed-cistern visual prototype, not a validated hydraulic/plumbing asset.','Native bowl/seat/cover/stand geometry retained; rear support needs contact andnormal review.','No room replacement,door-angle collision or navigation acceptance.'],'views':views},indent=2));print('Compact native WC prototype',before,after,flush=True)
