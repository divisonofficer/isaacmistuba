"""Actual native35mm casing profile replaces overwide173mm decorative architrave."""
import bpy,json,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'modules/infinigen'));sys.path.insert(0,str(Path(__file__).parent))
from infinigen.assets.objects.elements.doors.casing import DoorCasingFactory
from infinigen.core.constraints.constraint_language.constants import RoomConstants
from infinigen.core.util.math import FixedSeed
from bathroom_access_contract100 import DOORS,assess_wc
from wc_layout_checks import bounds
from compact_wc_contract import mesh_geometry_hash
D=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';m=json.load(open(D/'realism_refinement_r102.json'));source=Path(m['candidate']);out=source.with_name('scene_candidate_r103.blend');assert not out.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();assert sha(source)==m['candidate_sha256'];bpy.ops.wm.open_mainfile(filepath=str(source));case=bpy.data.objects[DOORS['101_bathroom1'].replace('GlassPanelDoorFactory','DoorCasingFactory')];oldbox=[list(v) for v in bounds(case)];materials=list(case.data.materials);mapping=json.load(open(D/'room_mapping.json'));opening=m['wc_access100']['additional_101_opening_relocation']['new_opening_y_m'];constants=RoomConstants();constants.door_width=opening[1]-opening[0];constants.door_size=2.355419635772705;constants.wall_thickness=.2290694
f=DoorCasingFactory(1275309,constants=constants);f.margin=.035;f.extrude=.005;f.bevel_all_sides=True
with FixedSeed(1275309):proto=f.create_asset()
assert max(abs(v-1) for v in proto.scale)<1e-6;case.data=proto.data;case.data.materials.clear();old_case_origin=list(case.matrix_world.translation);matrix=case.matrix_world.copy();matrix.translation.y=sum(opening)/2;case.matrix_world=matrix
for material in materials:case.data.materials.append(material)
bpy.data.objects.remove(proto,do_unlink=True);bpy.context.view_layer.update();case['wc_access_native_casing_preset']='35mm architrave margin,5mm projection';record={'object':case.name,'factory':'infinigen.assets.objects.elements.doors.casing.DoorCasingFactory','factory_source_sha256':sha(ROOT/'modules/infinigen/infinigen/assets/objects/elements/doors/casing.py'),'parameters':{'door_width_m':constants.door_width,'door_height_m':constants.door_size,'wall_thickness_m':constants.wall_thickness,'architrave_margin_m':.035,'projection_m':.005,'bevel_all_sides':True},'old_origin_m':old_case_origin,'new_origin_m':list(case.matrix_world.translation),'old_bbox_m':oldbox,'new_bbox_m':[list(v) for v in bounds(case)],'mesh_geometry_sha256':mesh_geometry_hash(case.data),'vertices':len(case.data.vertices),'faces':len(case.data.polygons),'scale':list(case.scale),'reason':'Saved102 actual casing ray intrudes to0.33655m at bowl centre. Regenerate true native trim with normal35mm width instead of173mm ornate casing; do not shrink or move the adult toilet.'};records=[]
for o in bpy.context.scene.objects:
 if o.type=='MESH' and str(o.get('program_key','')).endswith('_wc'):
  key=o['program_key'][:-3];r=assess_wc(o,key,mapping[key]);records.append(r);print('CHECK103',key,r['pass'],r['path_min_clear_width_m'],flush=True);assert r['pass'],key
bpy.ops.wm.save_as_mainfile(filepath=str(out));m.update(source=str(source),source_sha256=sha(source),candidate=str(out),candidate_sha256=sha(out),change='Preserve all adult native WC products,positions and real aperture/leaf fixes. Replace101 small-bath overwide native architrave with actual DoorCasingFactory35mm margin/5mm projection profile,align its centre to the actual aperture,not a primitive stand-in. No promotion.',photorealism_accepted=False);m['wc_access100']['records']=records;m['wc_access100']['native_casing_r103']=record;(D/'realism_refinement_r103.json').write_text(json.dumps(m,indent=2));print('SAVED103',sha(out),flush=True)
