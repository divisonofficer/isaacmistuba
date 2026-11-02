"""Cut only actual skirting crossing relocated unit entries; preserve source/history."""
import bpy,json,hashlib,sys
from pathlib import Path
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from build_core_wc104_draft import cut_architecture
from wc_layout_checks import bounds
d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=base/'scene_candidate_r119_draft.blend';dst=base/'scene_candidate_r120_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src);bpy.ops.wm.open_mainfile(filepath=str(src));o=bpy.data.objects['skirtingboard_support'];assert not o.modifiers;fz=bounds(bpy.data.objects['hallway_0/1.floor'])[1].z;build=json.loads((d/'core_wc104_planning/draft_build.json').read_text());cuts=[];specs=[]
for unit,cx in [(101,9),(102,12.5)]:
 y0,y1=next(x for x in build['relocated_entrances'] if x['unit']==unit)['opening_y_m'];lo=(cx-.35,y0+.005,-.02);hi=(cx+.35,y1-.005,fz+.30);cuts.append((lo,hi));specs.append({'unit':unit,'cut_bounds_m':[lo,hi]})
record=cut_architecture(o,cuts);assert record;remaining=[]
for f in o.data.polygons:
 p=o.matrix_world@f.center
 if any(all(lo[k]+1e-6<p[k]<hi[k]-1e-6 for k in range(3)) for lo,hi in cuts):remaining.append(f.index)
assert not remaining;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==before;(d/'skirting120_portal_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'candidate':str(dst),'candidate_sha256':sha(dst),'object':'skirtingboard_support','cuts':specs,'clip_record':record,'scope':'Local actual rendered baseboard faces removed only inside relocated unit entry apertures; all other baseboard pieces/materials and per-loop UV interpolations retained. Source119 body/furniture unchanged. Cut end cap/architrave cover, expanded physical route including skirting and matched RGB still required. Earlier119 subset pass omitted this real obstruction and is superseded.','accepted':False},indent=2));print('RESIDENTIAL120_PORTAL_SKIRTING_CUT')
