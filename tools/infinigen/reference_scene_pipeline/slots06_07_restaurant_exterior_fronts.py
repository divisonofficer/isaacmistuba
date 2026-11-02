import bpy,json,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from cut_surface import remove_box_faces
W=R/'out/infinigen_v2/kr_large_restaurant_floor_07_48712507';src=W/'furnished_r12_calibrated.blend';out=W/'furnished_r13_portal_skins.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(src));inv=json.loads((W/'native_product_inventory_r12_calibrated.json').read_text());before={n:bpy.data.objects[n].matrix_world.copy()for p in inv['products']for n in p['objects']};rows=[]
for i in range(4):
 left=6+3.25*i;xc=left+1.625;room=f'dining-room_0/{i+1}';cz=min((bpy.data.objects[room+'.ceiling'].matrix_world@Vector(v)).z for v in bpy.data.objects[room+'.ceiling'].bound_box)
 for name in [room+'.exterior','living-room_0/0.exterior']:
  o=bpy.data.objects[name];o.data=o.data.copy();n=remove_box_faces(o,(xc,15,(.11+cz)/2),(3.03,.26,cz-.11+.01));rows.append({'object':name,'cut_center_xyz_m':[xc,15,(.11+cz)/2],'cut_dimensions_xyz_m':[3.03,.26,cz-.11+.01],'removed_split_faces':n})
# Explicitly materialize retained native envelope skins to the inferred matching plaster; retain geometry except exact portal cuts.
materials=[]
for o in bpy.data.objects:
 if o.type=='MESH'and o.name.endswith('.exterior'):
  old=[m.name for m in o.data.materials if m];o.data.materials.clear();o.data.materials.append(bpy.data.materials['Reference_inferred_warm_plaster']);materials.append({'object':o.name,'old':old,'new':'Reference_inferred_warm_plaster'})
for n,m in before.items():assert max(abs(m[i][j]-bpy.data.objects[n].matrix_world[i][j])for i in range(4)for j in range(4))<1e-7
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));(W/'native_product_inventory_r13_portal_skins.json').write_text(json.dumps(inv,indent=2));(W/'body_route_paths_r13_portal_skins.json').write_text((W/'body_route_paths_r12_calibrated.json').read_text());(W/'furnished_r13_portal_skins_views.json').write_text((W/'furnished_r12_calibrated_views.json').read_text());(W/'actual_portal_exterior_skin_fix_r13.json').write_text(json.dumps({'trigger':'R12actualRGBblackboothfronts;scene.ray_cast identifies livingroom.exterior closure left across broadened openings','source':str(src),'candidate':str(out),'actual_ray_evidence':'black_front_actual_ray_probe_r12.json','matching_measured_portal_cuts':rows,'retained_envelope_inferred_materials':materials,'all_native_furniture_matrices_unchanged':True,'prior_wall_only_route_scope_superseded':True,'acceptance':False},indent=2));print('NATIVE_EXTERIOR_PORTAL_SKINS_FIXED',flush=True)
