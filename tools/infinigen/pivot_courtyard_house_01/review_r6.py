"""Direct r5 findings: stable native beds, clear glazing, flat screen materials."""
import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner.proc_home import SoftBedFactory,FicusPlantFactory
base=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
fixes=[]
def bounds(o):
 pts=[o.matrix_world@Vector(v) for v in o.bound_box]
 return [(min(v[i] for v in pts),max(v[i] for v in pts)) for i in range(3)]
# Keep each original bed footprint and head end; replace the entire cloth family.
for idx,old in enumerate([o for o in bpy.data.objects if o.parent is None and 'BedFactory' in o.name and o.get('ir_room')]):
 rid=old['ir_room'];b=bounds(old);cx=(b[0][0]+b[0][1])/2;cy=(b[1][0]+b[1][1])/2
 alongx=b[0][1]-b[0][0]>b[1][1]-b[1][0]
 fac=SoftBedFactory(48712600+idx);fac.throw_rgb=(.34,.30,.24)
 new=fac.spawn_asset(900+idx)
 if alongx:
  new.rotation_euler.z=0;new.location=(b[0][0],cy,.14754218);length=b[0][1]-b[0][0];width=b[1][1]-b[1][0]
 else:
  positive=rid=='bedroom_0/4';new.rotation_euler.z=math.pi/2 if positive else -math.pi/2
  new.location=(cx,b[1][0] if positive else b[1][1],.14754218);length=b[1][1]-b[1][0];width=b[0][1]-b[0][0]
 new.scale.x=length/2.18;new.scale.y=width/2.2;new['ir_room']=rid
 for x in reversed([old,*old.children_recursive]):bpy.data.objects.remove(x,do_unlink=True)
 fixes.append({'issue':'angular tangled cloth','room':rid,'action':'engine SoftBedFactory with preserved original bed footprint','object':new.name})
# Replace the complete legacy glass node tree: old shader was not necessarily Principled.
glass=bpy.data.materials.new('pivot_r6_clear_thin_glass');glass.use_nodes=True
nt=glass.node_tree;nt.nodes.clear();out=nt.nodes.new('ShaderNodeOutputMaterial');tr=nt.nodes.new('ShaderNodeBsdfTransparent');tr.inputs[0].default_value=(.96,.98,1,1)
nt.links.new(tr.outputs[0],out.inputs['Surface'])
window_count=0
for o in bpy.data.objects:
 if o.type!='MESH':continue
 if 'WindowFactory' in o.name:
  for sl in o.material_slots:
   if sl.material and 'glass' in sl.material.name.lower() and 'frost' not in sl.material.name.lower():sl.material=glass;window_count+=1
 # Flat dark screen, no random print displacement/normal.
 if 'OfficeDeskFactory' in o.name:
  o.data=o.data.copy()
  for sl in o.material_slots:
   if sl.material and 'screen' in sl.material.name.lower():sl.material=pa._flat('pivot_r6_monitor_screen',(.012,.019,.026),.3)
fixes.append({'issue':'opaque residential window appearance','action':'thin transparent glazing for non-bath windows','slots_changed':window_count})
# Remove native window blind families only, keeping frames, glass, doors, and walls.
removed=[]
for o in list(bpy.data.objects):
 if any(k in o.name.lower() for k in ('blindsfactory','blindfactory')):
  removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
# Smooth neutral ceiling finish instead of mottled stone/plaster shader.
ceiling=pa._flat('pivot_r6_matte_ceiling',(.78,.76,.71),.95)
for o in bpy.data.objects:
 if o.type=='MESH' and o.name.endswith('.ceiling'):o.data=o.data.copy();o.data.materials.clear();o.data.materials.append(ceiling)
# Landscape stays outside the authored footprint; native procedural plants.
for i,(x,y,scale) in enumerate([(3,26,3.4),(8,26,4.0),(13,26,3.8),(18,26,4.2),(24,27,3.6)]):
 tree=FicusPlantFactory(48712700+i).spawn_asset(920+i);tree.location=(x,y,.14);tree.scale=(scale,scale,scale);tree['pivot_external_landscape']=True
bpy.context.view_layer.update()
# Evidence for subsequent placement revision; no guessing at the media family name.
root_objects=[{'name':o.name,'room':o.get('ir_room'),'bounds':bounds(o),'materials':[m.name if m else None for m in o.data.materials]} for o in bpy.data.objects if o.type=='MESH' and o.parent is None and (o.get('ir_room') in ('living-room_0/1','office_0/0') or any(k in o.name.lower() for k in ('blind','media')))]
bpy.context.scene['pivot_revision']='r6_direct_review'
out=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full/scene_review_r6.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(out))
(base/'revision_r6.json').write_text(json.dumps({'fixes':fixes,'blinds_removed':removed,'root_objects':root_objects,'limitations':['Thin transparent glazing approximation omits glass reflections/refraction; suitable for current layout review, not physical glass sensor ground truth.','TV placement and study desk count remain to inspect after this round.']},indent=2))
print('PIVOT_R6_COMPLETE',flush=True)
