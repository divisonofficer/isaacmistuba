"""Replace visibly mottled procedural steel with properly projected scan normals."""
import bpy,json,sys,shutil,argparse
from pathlib import Path
from material_detail import scanned_steel
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);a=p.parse_args()
office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;previous=14 if office else 12;revision=15 if office else 13
base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;asset=ref/'pbr_assets/metal_0038';asset.mkdir(parents=True,exist_ok=True)
for filename in ('base_color.jpg','roughness.jpg','normal_gl.png'):
 dest=asset/filename
 if not dest.exists():shutil.copy2(ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/pbr_assets/metal_0038'/filename,dest)
bpy.ops.wm.open_mainfile(filepath=str(base/f'scene_candidate_r{previous}.blend'))
new=scanned_steel(ref/'pbr_assets');changes=[]
for o in bpy.data.objects:
 if o.type!='MESH':continue
 for slot in o.material_slots:
  if slot.material and slot.material.name.startswith(('ReferencePBR_brushed_stainless','res03_lift_steel','ir_chrome','ir_kit_steel','ir_kit_fridge')):
   changes.append({'object':o.name,'old':slot.material.name});slot.material=new
out=base/f'scene_candidate_r{revision}.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/f'material_detail_r{revision}.json').write_text(json.dumps({'source':f'scene_candidate_r{previous}.blend','steel_scan':'metal_0038 roughness and GL normal, project-local','normal_projection':'Three planar world-basis perturbations; flat normal preserves original shading N. No UV assumption on joined factory meshes.','roughness_range':[.24,.34],'normal_strength':.2,'changes':changes,'visual_acceptance':False},indent=2))
