"""r6 review: reject giant planters, clear deck sightline, repair monitor overlap."""
import bpy,bmesh,json,math,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
base=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';fixes=[]
def remove(o):
 for x in reversed([o,*o.children_recursive]):bpy.data.objects.remove(x,do_unlink=True)
def bounds(o):
 pts=[o.matrix_world@Vector(v) for v in o.bound_box]
 return [(min(v[i] for v in pts),max(v[i] for v in pts)) for i in range(3)]
# r6 landscape is a rejected experiment: a scaled pot is not a landscape tree.
removed=[]
for o in list(bpy.data.objects):
 if o.get('pivot_external_landscape'):removed.append(o.name);remove(o)
fixes.append({'issue':'r6 regression: giant outdoor planters','action':'remove all 5 experimental scaled Ficus families','objects':removed})
for o in list(bpy.data.objects):
 if o.get('ir_room')=='living-room_0/1' and 'MediaWallFactory' in o.name:
  fixes.append({'issue':'TV panel obstructed the deck window','action':'remove media panel; preserve original fireplace on east wall','object':o.name});remove(o)
# Two seating faces are closer to the reference than the isolated side chair.
for o in list(bpy.data.objects):
 if o.get('ir_room')=='living-room_0/1' and 'AboArmchairFactory' in o.name:remove(o)
sofa=next(o for o in bpy.data.objects if o.get('ir_room')=='living-room_0/1' and o.name.startswith('AboSofaFactory'))
new=sofa.copy();new.data=sofa.data.copy();bpy.context.scene.collection.objects.link(new)
new.name='PivotSecondSofaFactory(1001).spawn_asset(1001)';new.rotation_euler.z-=math.pi/2
bpy.context.view_layer.update();b=bounds(new);new.location+=Vector((16.16-(b[0][0]+b[0][1])/2,14.85-(b[1][0]+b[1][1])/2,.147551-b[2][0]));new['ir_room']='living-room_0/1'
for o in bpy.data.objects:
 if o.get('ir_room')=='living-room_0/1' and any(k in o.name for k in ('AboCoffeeFactory','AboRugFactory')):o.location.y+=.55
fixes.append({'issue':'sparse living arrangement','action':'reuse native sofa asset for western loveseat; shift rug and coffee table +0.55 m'})
# Master headboard at north side, as in the floorplan; keep room dimensions.
master=next(o for o in bpy.data.objects if o.get('ir_room')=='bedroom_0/3' and 'SoftBedFactory' in o.name)
master.rotation_euler.z=-math.pi/2;master.scale.x=2.15/2.18;master.scale.y=1.9/2.2;master.location=(22.15,22.45,.14754218)
# Native window factory embeds its blind slats as disconnected thin components.
slats=0
for o in bpy.data.objects:
 if o.type!='MESH' or 'WindowFactory' not in o.name:continue
 # Preserve frosted wet-room glazing.
 if any(m and 'frost' in m.name.lower() for m in o.data.materials):continue
 bb=bounds(o);horizontal=(bb[0][1]-bb[0][0])>(bb[1][1]-bb[1][0]);axis=0 if horizontal else 1
 bm=bmesh.new();bm.from_mesh(o.data);seen=set();delete=[]
 for v in bm.verts:
  if v in seen:continue
  comp=[];todo=[v];seen.add(v)
  while todo:
   cur=todo.pop();comp.append(cur)
   for edge in cur.link_edges:
    other=edge.other_vert(cur)
    if other not in seen:seen.add(other);todo.append(other)
  pts=[o.matrix_world@v.co for v in comp];zz=[p.z for p in pts];span=max(p[axis] for p in pts)-min(p[axis] for p in pts)
  if span>.4 and max(zz)-min(zz)<.045 and min(zz)>bb[2][0]+.08 and max(zz)<bb[2][1]-.08:delete.extend(comp);slats+=1
 if delete:bmesh.ops.delete(bm,geom=delete,context='VERTS')
 bm.to_mesh(o.data);bm.free();o.data.update()
# Resolve monitor mesh overlap. Factory front panel sat behind its backing;
# add a separate planar display 2 cm ahead of the backing, using same engine primitives.
screen=pa._flat('pivot_r7_display_matte',(.018,.028,.04),.55)
for o in list(bpy.data.objects):
 if o.get('ir_room')=='office_0/0' and 'OfficeDeskFactory(60)' in o.name:remove(o)
 elif o.get('ir_room')=='office_0/0' and 'OfficeChairFactory' in o.name and '(36)' in o.name:remove(o)
desk=next(o for o in bpy.data.objects if o.get('ir_room')=='office_0/0' and 'OfficeDeskFactory' in o.name)
# Native seed 58 desk has a single display; local origin is factory origin.
face=pa._prims('PivotMonitorFaceFactory(1002).spawn_asset(1002)',[(screen,[('box',(-.376+.235,0,1.08),(.008,.54,.305),(0,0,0))])])
face.matrix_world=desk.matrix_world.copy();face['ir_room']='office_0/0'
# Oak desktop is closer to the study reference, with one workstation.
for sl in desk.material_slots:
 if sl.material and 'desk_top' in sl.material.name:sl.material=pa._flat('pivot_r7_study_oak',(.48,.34,.22),.6,wood=True)
fixes.append({'issue':'screen backing overlaps display and study clutter','action':'remove second desk/chair, add display in front of backing','blind_components_removed':slats})
# Retain old cameras for paired comparison; add a master view with the full bed.
views=json.loads((ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full/review_views_r3.json').read_text())
views.append({'name':'master_reference_wide','location':[22.1,19.35,1.65],'target':[22.15,21.75,1.15],'hfov':80})
views.append({'name':'living_reference_wide','location':[19.7,11.85,1.65],'target':[17.5,16.7,1.2],'hfov':85})
(ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full/review_views_r7.json').write_text(json.dumps(views,indent=2))
bpy.context.view_layer.update()
invalid=[o.name for o in bpy.data.objects if o.type=='MESH' and any(not math.isfinite(x) or abs(x)>100 for x in o.dimensions)]
assert not invalid,invalid
bpy.context.scene['pivot_revision']='r7_direct_review'
bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full/scene_review_r7.blend'))
(base/'revision_r7.json').write_text(json.dumps({'fixes':fixes,'invalid_mesh_extents':invalid,'limitations':['Clear thin glazing approximation retained','Exterior landscape remains incomplete after rejected giant-planter experiment','Study monitor face placement and second sofa require direct render inspection']},indent=2))
print('PIVOT_R7_COMPLETE',flush=True)
