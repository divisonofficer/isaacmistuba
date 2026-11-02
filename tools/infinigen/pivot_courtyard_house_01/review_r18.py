"""Remove leftover native rigid throw side panels; rebuild laundry round details at 64 segments."""
import bpy,bmesh,math,json,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'));from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';removed=[]
for bed in [o for o in bpy.data.objects if o.parent is None and 'SoftBedFactory' in o.name]:
 bm=bmesh.new();bm.from_mesh(bed.data);seen=set();delete=[]
 for v in bm.verts:
  if v in seen:continue
  todo=[v];seen.add(v);comp=[]
  while todo:
   c=todo.pop();comp.append(c)
   for e in c.link_edges:
    q=e.other_vert(c)
    if q not in seen:seen.add(q);todo.append(q)
  lo=[min(v.co[k] for v in comp) for k in range(3)];hi=[max(v.co[k] for v in comp) for k in range(3)]
  # Native SoftBedFactory throw side drops: x1.325..1.775, y~+/- .99,
  # material slot5. Keep all headboard, pillows, mattress and authored drape.
  mats={f.material_index for v in comp for f in v.link_faces}
  if mats=={5} and lo[0]>1.2 and hi[0]<1.9 and hi[1]-lo[1]<.15:
   delete.extend(comp);removed.append({'bed':bed.name,'lo':lo,'hi':hi,'vertices':len(comp)})
 if delete:bmesh.ops.delete(bm,geom=delete,context='VERTS')
 bm.to_mesh(bed.data);bm.free();bed.data.update()
white=bpy.data.materials['pivot_r16_appliance_enamel'];steel=bpy.data.materials['pivot_r14_brushed_hardware'];dark=bpy.data.materials['pivot_r16_dark_glass'];fz=.14754
for i,(x,role) in enumerate([(8.65,'washing_machine'),(9.30,'tumble_dryer')]):
 for o in list(bpy.data.objects):
  if o.get('ir_role')==role:
   for c in list(o.children_recursive):bpy.data.objects.remove(c,do_unlink=True)
   bpy.data.objects.remove(o,do_unlink=True)
 body=pa._prims(f'PivotLaundryApplianceFactory({2200+i}).spawn_asset({2200+i})',[(white,[('box',(x,11.02,fz+.43),(.60,.62,.84),(0,0,0))]),(dark,[('box',(x+.08,10.696,fz+.75),(.16,.014,.052),(0,0,0))])]);body['ir_room']='utility_0/0';body['ir_role']=role
 # True toroidal chrome rim (axis Y), rounded profile and circular silhouette.
 verts=[];faces=[]
 for j in range(64):
  a=2*math.pi*j/64
  for k in range(12):
   t=2*math.pi*k/12;rad=.205+.018*math.cos(t);verts.append((x+rad*math.cos(a),10.677+.018*math.sin(t),fz+.40+rad*math.sin(a)))
 for j in range(64):
  for k in range(12):faces.append((j*12+k,((j+1)%64)*12+k,((j+1)%64)*12+(k+1)%12,j*12+(k+1)%12))
 me=bpy.data.meshes.new('laundry_circular_rim');me.from_pydata(verts,[],faces);me.materials.append(steel)
 o=bpy.data.objects.new(f'PivotLaundryRim_{i}',me);bpy.context.scene.collection.objects.link(o);o.parent=body
 for p in me.polygons:p.use_smooth=True
 for name,cx,cz,rad,dep,ma in [('door',x,fz+.40,.187,.016,dark),('dial',x-.20,fz+.745,.025,.020,steel)]:
  bm=bmesh.new();res=bmesh.ops.create_cone(bm,cap_ends=True,segments=64,radius1=rad,radius2=rad,depth=dep)
  for v in bm.verts:xx,yy,zz=v.co;v.co=(cx+xx,10.679+zz,cz+yy)
  for f in bm.faces:f.smooth=len(f.verts)==4
  me=bpy.data.meshes.new('laundry_'+name);bm.to_mesh(me);bm.free();me.materials.append(ma);o=bpy.data.objects.new(f'PivotLaundry_{name}_{i}',me);bpy.context.scene.collection.objects.link(o);o.parent=body
bpy.context.view_layer.update();bad=[o.name for o in bpy.data.objects if o.type=='MESH' and any(not math.isfinite(v) or abs(v)>100 for v in o.dimensions)];assert not bad,bad
bpy.context.scene['pivot_revision']='r18_bedding_laundry_geometry';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_review_r18.blend'))
(B/'revision_r18.json').write_text(json.dumps({'removed_rigid_throw_components':removed,'laundry_rim_segments':64,'invalid_mesh_dimensions':bad,'floorplan_changed':False},indent=2));print('PIVOT_R18_COMPLETE',flush=True)
