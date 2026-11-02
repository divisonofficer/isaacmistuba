"""Reference fit: draped bedding, island seating, oak coffee set, clean sightlines."""
import bpy,bmesh,json,math,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner.proc_home import LinearPendantFactory,RecessedSpotFactory,StoneCoffeeTableFactory
base=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';run=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full';fixes=[]
pa.SURFACE_DETAIL=False

def material(name,rgb,rough=.7,metal=0):
 m=bpy.data.materials.new(name);m.use_nodes=True;bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(*rgb,1);bs.inputs['Roughness'].default_value=rough;bs.inputs['Metallic'].default_value=metal;return m

def remove(o):
 for q in reversed([o,*o.children_recursive]):bpy.data.objects.remove(q,do_unlink=True)
def bounds(o):
 pts=[o.matrix_world@Vector(v) for v in o.bound_box]
 return [(min(v[i] for v in pts),max(v[i] for v in pts)) for i in range(3)]
linen=material('pivot_r11_woven_linen',(.72,.68,.59),.94);throwmat=material('pivot_r11_taupe_throw',(.35,.31,.25),.95)
for m in (linen,throwmat):
 nt=m.node_tree;bs=nt.nodes.get('Principled BSDF');noise=nt.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=260;noise.inputs['Detail'].default_value=2;bump=nt.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.001;nt.links.new(noise.outputs['Fac'],bump.inputs['Height']);nt.links.new(bump.outputs['Normal'],bs.inputs['Normal'])
cloth_count=0
for bed in [o for o in bpy.data.objects if o.parent is None and o.get('ir_room') and 'SoftBedFactory' in o.name]:
 bm=bmesh.new();bm.from_mesh(bed.data);seen=set();delete=[]
 for v in bm.verts:
  if v in seen:continue
  comp=[];todo=[v];seen.add(v)
  while todo:
   cur=todo.pop();comp.append(cur)
   for e in cur.link_edges:
    other=e.other_vert(cur)
    if other not in seen:seen.add(other);todo.append(other)
  lo=[min(v.co[i] for v in comp) for i in range(3)];hi=[max(v.co[i] for v in comp) for i in range(3)];mx=(hi[0]+lo[0])/2
  if hi[1]-lo[1]>1.7 and hi[2]>.6 and lo[2]>.30 and (hi[0]-lo[0]>1 or mx>1.3):delete.extend(comp)
 if delete:bmesh.ops.delete(bm,geom=delete,context='VERTS')
 bm.to_mesh(bed.data);bm.free();bed.data.update()
 for band in (False,True):
  nx,ny=48,54;verts=[];faces=[];x0,x1=(1.35,1.85) if band else (.52,2.22)
  for ix in range(nx+1):
   x=x0+(x1-x0)*ix/nx
   for iy in range(ny+1):
    y=-1.10+2.20*iy/ny;side=max(0,(abs(y)-.91)/.19);foot=max(0,(x-2.03)/.19)
    z=.646+(.018 if band else 0)-.27*min(side,1)**.75-.27*min(foot,1)**.75
    z+=.007*math.sin(18*y+1.8*x)*math.sin(3.1*x)+.004*math.cos(24*x+5*y)
    verts.append((x,y,z))
  for ix in range(nx):
   for iy in range(ny):
    i=ix*(ny+1)+iy;faces.append((i,i+ny+1,i+ny+2,i+1))
  me=bpy.data.meshes.new('pivot_draped_linen');me.from_pydata(verts,[],faces);me.update();o=bpy.data.objects.new(('PivotThrowFactory' if band else 'PivotDuvetFactory')+str(cloth_count),me);bpy.context.scene.collection.objects.link(o);o.parent=bed;o['ir_room']=bed['ir_room'];o.data.materials.append(throwmat if band else linen)
  for f in me.polygons:f.use_smooth=True
  solid=o.modifiers.new('cloth thickness','SOLIDIFY');solid.thickness=.008
  sub=o.modifiers.new('soft fabric surface','SUBSURF');sub.levels=1;sub.render_levels=1;cloth_count+=1
for m in bpy.data.materials:
 if m.name.startswith('ir_sfb_petrol') and m.use_nodes:
  bs=m.node_tree.nodes.get('Principled BSDF')
  if bs:
   for link in list(bs.inputs['Base Color'].links):m.node_tree.links.remove(link)
   bs.inputs['Base Color'].default_value=(.24,.28,.21,1)
fixes.append({'issue':'native bed quilts read as rigid flat blocks','action':'retain engine bed frames and cushions, replace cover meshes with gently draped finite cloth surfaces; woven linen and taupe throw','cloth_meshes':cloth_count})
# Remove the original open leaf, now superseded by the closed privacy door.
old=bpy.data.objects.get('PanelDoorFactory(2248688).spawn_asset(15)')
if old:remove(old)
# Hooks were placed across wardrobe side panels; closet storage already exists.
for o in list(bpy.data.objects):
 if o.get('ir_room')=='closet_0/0' and 'ClinicWallItemFactory' in o.name:remove(o)
# Closed WC needs its own ceiling light, rather than borrowed corridor light.
spot=RecessedSpotFactory().spawn_asset(1401);spot.location=(5.4,14.75,2.9)
ld=bpy.data.lights.new('pivot_wc_ceiling','AREA');ld.energy=35;ld.shape='DISK';ld.size=.35;lamp=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(lamp);lamp.location=(5.4,14.75,2.78)
fixes.append({'issue':'guest interior camera blocked by old duplicate door, WC dark after closing door, closet hooks overlap storage','action':'remove old guest door leaf and redundant closet hooks; add real WC ceiling area light'})
# Island seating: 3 native light-wood counter stools, outside counter footprint.
island=next(o for o in bpy.data.objects if 'KitchenIslandFactory' in o.name);b=bounds(island);cx=(b[0][0]+b[0][1])/2;cy=(b[1][0]+b[1][1])/2
pa.STYLE['chair_style']='light_wood'
for i,x in enumerate((cx-.60,cx,cx+.60)):
 stool=pa.CounterStoolFactory(48713100+i).spawn_asset(1410+i);stool.location=(x,b[1][1]+.43,.14754);stool.rotation_euler.z=-math.pi/2;stool['ir_room']='dining-room_0/0'
pend=LinearPendantFactory(drop=.6).spawn_asset(1415);pend.location=(cx,cy,2.92);pend.rotation_euler.z=math.pi/2
# A light oak plinth coffee table and neutral textile rug align with living ref.
for o in list(bpy.data.objects):
 if o.get('ir_room')=='living-room_0/1' and 'AboCoffeeFactory' in o.name:remove(o)
table=StoneCoffeeTableFactory(48713120).spawn_asset(1420);table.location=(18,13.85,.14754);table.rotation_euler.z=math.pi/2;table['ir_room']='living-room_0/1'
oak=pa._flat('pivot_r11_light_oak',(.48,.34,.20),.58,wood=True)
for slot in table.material_slots:slot.material=oak
rugmat=material('pivot_r11_natural_rug',(.39,.34,.26),.95)
for o in bpy.data.objects:
 if o.get('ir_room')=='living-room_0/1' and 'AboRugFactory' in o.name:o.scale.y*=1.55;o.data=o.data.copy();o.data.materials.clear();o.data.materials.append(rugmat)
# Subdued smooth ceiling finish. Native mesh detail was too coarse under lamps.
ceiling=material('pivot_r11_smooth_ceiling',(.78,.76,.71),.95)
for o in bpy.data.objects:
 if o.type=='MESH' and o.name.endswith('.ceiling'):o.data=o.data.copy();o.data.materials.clear();o.data.materials.append(ceiling)
fixes.append({'issue':'missing breakfast seats and sparse living set; coarse ceiling finish','action':'3 native stools and linear island pendant, light oak coffee table, neutral larger rug, smooth ceiling'})
views=json.loads((run/'review_views_r10.json').read_text())
for v in views:
 if v['name']=='closet_0-0_wide0':v.update(location=[23.7,18.75,1.65],target=[23.7,17.35,1.25],hfov=90)
(run/'review_views_r11.json').write_text(json.dumps(views,indent=2))
bpy.context.view_layer.update();invalid=[o.name for o in bpy.data.objects if o.type=='MESH' and any(not math.isfinite(v) or abs(v)>100 for v in o.dimensions)];assert not invalid,invalid
bpy.context.scene['pivot_revision']='r11_reference_fit';bpy.ops.wm.save_as_mainfile(filepath=str(run/'scene_review_r11.blend'))
(base/'revision_r11.json').write_text(json.dumps({'fixes':fixes,'invalid_mesh_extents':invalid,'island_bounds':b,'camera_changes':['closet_0-0_wide0'],'camera_count':len(views),'limitations':['Native procedural furniture remains an approximation of generated reference photos','Estimated floorplan dimensions unchanged']},indent=2));print('PIVOT_R11_COMPLETE',flush=True)
