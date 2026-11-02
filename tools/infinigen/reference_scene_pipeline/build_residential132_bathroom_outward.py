"""Native frame826 + original820mm leaf, actual3mm jamb gaps and outward100deg pose."""
import bpy,bmesh,json,hashlib,math,sys
from pathlib import Path
from mathutils import Vector,Matrix
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from compact_wc_contract import mesh_geometry_hash
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';base=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=base/'scene_candidate_r130_draft.blend';dst=base/'scene_candidate_r132_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();before=sha(src);m=json.loads((D/'bathroom130_native_door_measurement.json').read_text());assert m['source_sha256']==before;y0,z0,y1,z1=m['actual_apertures'][0]['yz_bbox_m'];fz=.1145347
bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();old={o.name:([list(v) for v in o.matrix_world],mesh_geometry_hash(o.data) if o.type=='MESH' else None) for o in bpy.context.scene.objects};removed='LiteDoorFactory(800570).spawn_asset(6)';bpy.data.objects.remove(bpy.data.objects[removed],do_unlink=True)
def append_part(folder,label,attribute):
 asset=D/folder/'native_asset.blend';c=json.loads((asset.parent/'native_contract.json').read_text())
 with bpy.data.libraries.load(str(asset),link=False) as (av,loaded):loaded.objects=[c['object']]
 o=loaded.objects[0];bpy.context.scene.collection.objects.link(o);bpy.context.view_layer.update();M=o.matrix_world.copy();o.parent=None;o.matrix_world=M;o.name=label;o['program_key']='101_bathroom2_door';o['audit_kind']='architecture';attr=o.data.attributes[attribute];keep={v.index for v in o.data.vertices if attr.data[v.index].value};bm=bmesh.new();bm.from_mesh(o.data);bm.faces.ensure_lookup_table();drop=[f for f in bm.faces if not all(v.index in keep for v in f.verts)];bmesh.ops.delete(bm,geom=drop,context='FACES_ONLY');bmesh.ops.delete(bm,geom=[v for v in bm.verts if not v.link_faces],context='VERTS');bm.to_mesh(o.data);bm.free();o.data.update();bpy.context.view_layer.update();return o,{'source':str(asset),'source_sha256':sha(asset),'selected_native_attribute':attribute,'post_generation_scaling':False}
def points(o):return [o.matrix_world@v.co for v in o.data.vertices]
def bounds(o):
 p=points(o);return Vector([min(v[k] for v in p) for k in range(3)]),Vector([max(v[k] for v in p) for k in range(3)])
frame,fp=append_part('native_bathroom_frame132','Residential132_101_bathroom2_native_fixed_frame','door_frame');lo,hi=bounds(frame);frame.matrix_world=Matrix.Translation(Vector((3.-(lo.x+hi.x)/2,(y0+y1)/2-(lo.y+hi.y)/2,z1-.003-hi.z)))@frame.matrix_world;bpy.context.view_layer.update();inv=frame.matrix_world.inverted();embedded=0
for v in frame.data.vertices:
 p=frame.matrix_world@v.co
 if p.z<fz+.03:v.co=inv@(p-Vector((0,0,.04)));embedded+=1
frame.data.update()
leaf,lp=append_part('native_bedroom2_door130','Residential132_101_bathroom2_native_leaf_lever','door_left');ids=[v.index for v in leaf.data.vertices if leaf.data.attributes['door'].data[v.index].value];p=[leaf.matrix_world@leaf.data.vertices[i].co for i in ids];lo=Vector([min(v[k] for v in p) for k in range(3)]);hi=Vector([max(v[k] for v in p) for k in range(3)]);leaf.matrix_world=Matrix.Translation(Vector((3.-(lo.x+hi.x)/2,(y0+y1)/2-(lo.y+hi.y)/2,fz+.008-lo.z)))@leaf.matrix_world;bpy.context.view_layer.update();closed=points(leaf);p=[closed[i] for i in ids];lo=Vector([min(v[k] for v in p) for k in range(3)]);hi=Vector([max(v[k] for v in p) for k in range(3)]);hinge=Vector((hi.x+.003,lo.y,0));rotation=Matrix.Rotation(math.radians(-100),4,'Z');inverse=leaf.matrix_world.inverted();expected=[hinge+rotation@(p-hinge) for p in closed]
for v,p in zip(leaf.data.vertices,expected):v.co=inverse@p
leaf.data.update();bpy.context.view_layer.update();error=max((a-b).length for a,b in zip(points(leaf),expected));assert error<1e-5
# Native fixed frame profile is wider by6mm, original leaf is rigid and unscaled.
frlo,frhi=bounds(frame);nominal_jamb_gap=((frhi.y-frlo.y)-.08-.82)/2;assert abs(nominal_jamb_gap-.003)<1e-5
for o in bpy.context.scene.objects:
 if o.name in old:
  M,h=old[o.name];assert M==[list(v) for v in o.matrix_world],o.name
  if o.type=='MESH':assert h==mesh_geometry_hash(o.data),o.name
bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==before
row={'unit':101,'new_object':leaf.name,'fixed_frame_object':frame.name,'removed_wrong_double_assembly':removed,'kept_native_casing':'DoorCasingFactory(800570).spawn_asset(6)','source_aperture_yz_m':[y0,z0,y1,z1],'native_leaf_width_height_depth_m':[.82,2.3,.045],'frame_requested_clear_width_m':.826,'nominal_closed_leaf_side_gap_m':nominal_jamb_gap,'floor_leaf_gap_m':.008,'header_rough_gap_m':.003,'frame_bbox_m':[list(frlo),list(frhi)],'open_deg':-100,'hinge_world_m':list(hinge),'hinge_axis_offset_beyond_positive_leaf_face_m':.003,'max_world_rigid_pose_error_m':error,'fixed_lower_frame_embedded_points':embedded,'frame_provenance':fp,'leaf_provenance':lp,'post_generation_rescaling':False}
(D/'bathroom_door132_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'candidate':str(dst),'candidate_sha256':sha(dst),'rows':[row],'unrelated_raw_geometry_and_matrices_unchanged':True,'accepted':False,'scope':'Native826mm frame and original820mm leaf/lever combined without rescaling. Frame fixed, leaf rigid100deg outward with3mm jamb gaps and3mm external hinge axis offset. Kinematic axis only; visible hinge hardware not added. No sweep/whole-navigation/photo acceptance until separately tested.'},indent=2));print('BATH132_NATIVE_OUTWARD_SAVED',row,flush=True)
