"""User-requested material detail revision, keeping layout and cameras fixed."""
import json
from pathlib import Path
import bpy
from material_detail import apply_office
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r9.blend'))
receipt=apply_office(ref/'pbr_assets')
out=base/'scene_candidate_r10.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'material_detail_r10.json').write_text(json.dumps(receipt,indent=2));print('REFERENCE_MATERIAL_DETAIL',len(receipt['changes']),len(receipt['actual_beveled_objects']),flush=True)
