"""Real saved negative/positive texture-byte controls before chair RGB."""
import bpy,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[3];p=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_chair_candidates';repair=json.loads((p/'embedded_texture_repair.json').read_text());expected={}
for row in repair['repairs']:expected.setdefault(row['asset_id'],set()).add((row['png_sha256'],row['colorspace']))
reports=[]
for filename,should_pass in [('review_studio.blend',False),('review_studio_textures_fixed.blend',True)]:
 src=p/filename;bpy.ops.wm.open_mainfile(filepath=str(src));rows=[];errors=[]
 for asset,want in expected.items():
  actual=set();bad=[]
  for o in bpy.data.objects:
   if o.get('original_asset_id')!=asset:continue
   for slot in o.material_slots:
    if not slot.material or not slot.material.use_nodes:continue
    for node in slot.material.node_tree.nodes:
     if node.type!='TEX_IMAGE' or not node.image:continue
     im=node.image
     if not im.packed_file:bad.append(im.name);continue
     actual.add((hashlib.sha256(im.packed_file.data).hexdigest(),im.colorspace_settings.name))
  ok=not bad and actual==want;rows.append({'asset_id':asset,'expected_png_hash_and_colorspace':sorted(want),'actual':sorted(actual),'unpacked_images':sorted(set(bad)),'pass':ok})
  if not ok:errors.append(asset)
 passed=not errors;assert passed==should_pass,(filename,rows);reports.append({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'expected_pass':should_pass,'actual_pass':passed,'records':rows})
(p/'saved_texture_gate_validation.json').write_text(json.dumps({'actual_saved_scene_controls':reports,'scope':'Actual defective savedstudio rejected;actual fixedsavedstudio accepted for exact sourcePNG bytes+colorspace onABO shader image nodes. Does not prove material realism orscene fit.','photorealism_accepted':False},indent=2)+'\n');print('Saved texture negative/positive verified',flush=True)
