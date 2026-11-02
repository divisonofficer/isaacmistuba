import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];P=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r99.blend'
if not P.exists():P=P.with_name('scene_candidate_r128.blend')
with bpy.data.libraries.load(str(P),link=False) as (a,b):names=a.objects[:]
(R/'data/venue_refs/floor_plans_v3/skyline_penthouse_08/native_library_inventory.json').write_text(json.dumps({'source':str(P),'objects':names},indent=2));print('INVENTORY',P,len(names))
