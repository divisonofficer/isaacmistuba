"""Make relocated two-car garage physically usable: real vehicle opening, clearance depth and apron."""
import bpy,bmesh,json,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
# Preserve west storage and north service opening while extending only east end by 1m.
objects=[o for o in bpy.data.objects if o.type=='MESH' and (o.name=='garage_0/0' or o.name.startswith('garage_0/0.') or o.name=='PivotLayoutV2_garage_closed_old_connections')]
for o in objects:
 o.data=o.data.copy();inv=o.matrix_world.inverted()
 for v in o.data.vertices:
  p=o.matrix_world@v.co
  if p.x>=31.55:p.x+=1
  elif p.x>29.8:p.x+=(p.x-29.8)/(31.55-29.8)
  v.co=inv@p
for name in ['PivotSectionalGarageDoorFactory(1303).spawn_asset(1303)','PivotGarageV12_tracks_and_drive','PivotGarageV21_ceiling_supports']:bpy.data.objects[name].location.x+=1
lamp=bpy.data.objects.get('PointLampFactory(added).spawn_asset(11)')
if lamp:lamp.location.x+=.5
caps=[]
for suffix in ['.wall','.exterior']:
 o=bpy.data.objects['garage_0/0'+suffix];bpy.ops.mesh.primitive_cube_add(size=1,location=(33,11.5,1.35));c=bpy.context.object;c.dimensions=(1.0,4.34,2.45);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);m=o.modifiers.new('real_vehicle_gate_opening','BOOLEAN');m.operation='DIFFERENCE';m.solver='EXACT';m.object=c;bpy.context.view_layer.objects.active=o;bpy.ops.object.modifier_apply(modifier=m.name);bpy.data.objects.remove(c,do_unlink=True)
 bm=bmesh.new();bm.from_mesh(o.data);remove=[]
 for f in bm.faces:
  p=o.matrix_world@f.calc_center_median();n=o.matrix_world.to_3x3()@f.normal
  if min(abs(p.x-32.5),abs(p.x-33.5))<.003 and abs(n.x)>.98 and 9.32<p.y<13.68 and .12<p.z<2.58:remove.append(f)
 caps.append({'object':o.name,'surface_caps_removed':len(remove)});bmesh.ops.delete(bm,geom=remove,context='FACES');bm.to_mesh(o.data);bm.free()
# Connect exterior walk to the driveway apron; slab foundations contact existing ground.
o=bpy.data.objects['PivotGarageV17_external_walk']
for v in o.data.vertices:
 if v.co.x>31.5:v.co.x+=1.95
concrete=bpy.data.materials['garage_v12_grey_concrete'];parts=[('box',((32.85501+37)/2,(8.85+14.5)/2,.035275),(37-32.85501,14.5-8.85,.22055),(0,0,0)),('box',(32.95,11.5,.035275),(.40,4.34,.22055),(0,0,0))]
o=pa._prims('PivotGarageV22_driveway_apron',[(concrete,parts)]);o['ir_room']='exterior_access'
# Prove the car opening through the actual architectural envelope, not just a door panel.
gate=bpy.data.objects['PivotSectionalGarageDoorFactory(1303).spawn_asset(1303)'];gate.hide_set(True);bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();hit,p,n,f,obj,mat=bpy.context.scene.ray_cast(dg,Vector((33.6,11.5,1.0)),Vector((-1,0,0)),distance=8);diagnostic={'object':obj.name if obj else None,'point':list(p),'gate_temporarily_hidden_for_diagnostic':True};gate.hide_set(False);assert hit and p.x<28,diagnostic
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v22';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v22.blend'))
(B/'garage_volume_stage_v22.json').write_text(json.dumps({'status':'geometry_saved_parking_and_visual_audit_pending','garage_bounds':[26.5,9,33,14],'depth_m':6.5,'width_m':5.0,'changes':['One additional meter of garage depth for two useful parking envelopes','Actual 4.34m vehicle opening through both wall skins','Gate, tracks and ceiling supports moved together','Exterior walk joined to driveway apron'],'vehicle_opening_ray':diagnostic,'surface_caps':caps,'remaining':['Two-car envelope clearance audit','Updated exterior and full-house render review','Final plan and registration consistency']},indent=2)+'\n');print('PIVOT_GARAGE_VOLUME_V22_SAVED',diagnostic,flush=True)
