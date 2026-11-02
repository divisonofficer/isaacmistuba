import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/skyline_penthouse_08';P=R/'out/infinigen_v2/kr_skyline_penthouse_08_48712508/full/scene_candidate_r001.blend'
bpy.ops.wm.open_mainfile(filepath=str(P));(D/'architecture_inventory_r001.json').write_text(json.dumps([{'name':o.name,'type':o.type,'dimensions':list(o.dimensions)} for o in bpy.context.scene.objects if any(x in o.name.lower() for x in ['wall','window','floor','door','exterior'])],indent=2));print('ARCH_PROBE_SAVED')
