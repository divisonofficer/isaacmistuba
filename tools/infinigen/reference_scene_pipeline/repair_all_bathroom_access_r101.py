"""User request: full native adult products and eight bathroom access checks."""
import bpy,json,hashlib,sys,math
from pathlib import Path
from mathutils import Matrix,Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from wc_layout_checks import bounds
from compact_wc_contract import mesh_geometry_hash
from bathroom_access_contract100 import assess_wc,inner_room,set_leaf_angle,lower_small_bathroom_door
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';B=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';S=B/'scene_candidate_r97.blend';O=B/'scene_candidate_r101.blend';assert not O.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();hs=sha(S);contract=json.loads((D/'native_fullsize_wc100/contract.json').read_text());assert sha(contract['prototype_source'])==contract['prototype_source_sha256'];mapping=json.loads((D/'room_mapping.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(S))
with bpy.data.libraries.load(contract['prototype_source'],link=False) as (src,dst):dst.objects=[contract['object']]
proto=dst.objects[0];bpy.context.scene.collection.objects.link(proto);bpy.context.view_layer.update();assert mesh_geometry_hash(proto.data)==contract['mesh_geometry_sha256'];assert max(abs(v-1) for v in proto.scale)<1e-6
wcs=[o for o in bpy.context.scene.objects if o.type=='MESH' and str(o.get('program_key','')).endswith('_wc')];assert len(wcs)==8;removed=[];shifts=[]
def remove_tree(o):
 for ch in list(o.children):remove_tree(ch)
 removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
# Two small bathroom1 rooms have only790mm between shower side and opposite inner wall.
# Translate the complete native shower/accessory assembly18mm toward its side wall (still>=3mm gap).
for unit,delta in [(101,-.018),(102,.018)]:
 prefix=f'{unit}_bathroom1_shower';selected={o for o in bpy.context.scene.objects if str(o.get('program_key','')).startswith(prefix)}
 for root in list(selected):selected.update(root.children_recursive)
 assert selected
 for obj in selected:
  if obj.parent not in selected:
   mat=obj.matrix_world.copy();mat.translation+=Vector((delta,0,0));obj.matrix_world=mat
 shifts.append({'program':prefix,'delta_world_m':[delta,0,0],'objects':[o.name for o in selected]})
door_edits=[set_leaf_angle(key,mapping[key],leaf,angle) for key,leaf,angle in [('101_ensuite','door_left',-90),('101_bathroom2','door_right',90),('102_bathroom1','door_left',90)]]
opening_relocation=lower_small_bathroom_door(mapping['102_bathroom1'])
records=[]
for wc in wcs:
 key=wc['program_key'];roomkey=key[:-3];unit=int(key[:3]);oldlo,oldhi=bounds(wc);oldbounds=[list(oldlo),list(oldhi)];oldscale=list(wc.scale)
 for child in list(wc.children):remove_tree(child)
 for obj in list(bpy.context.scene.objects):
  if obj.get('wc_flush_parent_key')==key:remove_tree(obj)
 for k in list(wc.keys()):
  if k.startswith('wc_compact') or k.startswith('wc_flush'):del wc[k]
 for mod in list(wc.modifiers):wc.modifiers.remove(mod)
 wc.parent=None;wc.data=proto.data;wc.scale=(1,1,1);wc.rotation_euler=(0,0,0);wc.location=(0,0,oldlo.z);wc['wc_variant']='standard';wc['native_factory_product']='native_fullsize_wc100';wc['native_factory_source_sha256']=contract['factory_source_sha256'];wc['native_product_mesh_sha256']=contract['mesh_geometry_sha256'];wc['refinement_revision']=101
 if 'bathroom2' in roomkey:yaw=math.pi/2
 elif 'bathroom1' in roomkey:yaw=-math.pi/2
 else:yaw=0 if unit==101 else math.pi
 wc.rotation_euler.z=yaw;bpy.context.view_layer.update();lo,hi=bounds(wc);x0,y0,x1,y1=inner_room(mapping[roomkey]).bounds
 if 'bathroom2' in roomkey:
  wc.location.x+=(x0+x1)/2-(lo.x+hi.x)/2;wc.location.y+=y0+.020-lo.y
 elif 'bathroom1' in roomkey:
  shower=next(o for o in bpy.context.scene.objects if o.get('program_key')==f'{unit}_bathroom1_shower' and o.get('audit_kind')=='furniture');sl,sh=bounds(shower)
  targetx=(sh.x+x1)/2 if unit==101 else (x0+sl.x)/2
  wc.location.x+=targetx-(lo.x+hi.x)/2;wc.location.y+=y1-.020-hi.y
 else:
  wc.location.y+=(oldlo.y+oldhi.y-lo.y-hi.y)/2
  if unit==101:wc.location.x+=x0+.020-lo.x
  else:wc.location.x+=x1-.020-hi.x
 bpy.context.view_layer.update();assert max(abs(v-1) for v in wc.scale)<1e-6;assert mesh_geometry_hash(wc.data)==contract['mesh_geometry_sha256']
 row=assess_wc(wc,roomkey,mapping[roomkey]);row.update(old_bbox_m=oldbounds,old_scale=oldscale,native_product_mesh_identity=True,tank_included=True);records.append(row);print('WC100_ACCESS',key,'pass',row['pass'],'sides',row['side_left_m'],row['side_right_m'],'path',row['path_min_clear_width_m'],'doorarea',row['door_sweep_wc_overlap_m2'],flush=True)
 (D/'bathroom_access_r101_planning.json').write_text(json.dumps({'source':str(S),'source_sha256':hs,'records':records,'fixture_shifts':shifts,'removed_owned_parts':removed,'door_edits':door_edits,'opening_relocation':opening_relocation,'prototype_contract':contract,'saved_candidate':False},indent=2))
bpy.data.objects.remove(proto,do_unlink=True)
assert all(r['pass'] for r in records),[(r['key'],r['pass']) for r in records]
assert all(.37<r['width_m']<.39 and .65<r['depth_m']<.70 and .400<=r['seat_height_m']<=.420 for r in records)
bpy.ops.wm.save_as_mainfile(filepath=str(O));assert sha(S)==hs;meta=json.loads((D/'realism_refinement_r97.json').read_text());meta.update(source=str(S),source_sha256=hs,candidate=str(O),candidate_sha256=sha(O),change='User WC/access request:8 complete native full-tank adult products,scale1,configuredSI geometry. Two small-room shower assemblies translated18mm,three native leaf poses corrected,one small bathroom doorway translated100mm with complete jamb/grid-vertex aperture and tiling rebuild for requested clearances. Continuous bounded door sweeps and explicit>=600mm pedestrian routes checked in8rooms. No unapproved99pillow/104office changes inherited.',wc_access100={'prototype_contract':str(D/'native_fullsize_wc100/contract.json'),'prototype_sha256':contract['prototype_source_sha256'],'geometry_sha256':contract['mesh_geometry_sha256'],'records':records,'fixture_shifts':shifts,'removed_owned_parts':removed,'door_edits':door_edits,'opening_relocation':opening_relocation,'scope':'Geometric project requirements,not building-code,plumbing or mechanical certification. Independent saved-source audit andmatchedr22camera visual review still required.'},photorealism_accepted=False);(D/'realism_refinement_r101.json').write_text(json.dumps(meta,indent=2))
