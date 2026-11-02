"""Material-only native lamp controls, not photometric or room acceptance."""
import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/real_recessed_light_candidate';S=D/'review_studio.blend';rows=[]
for variant in ['ior_only','functional_unlit']:
 out=D/(variant+'.blend');assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(S));changes=[]
 for m in bpy.data.materials:
  if '8830afcbb0fd7442c0dd7a27c05129c65e0be283' not in m.name or not m.use_nodes:continue
  bs=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None);assert bs
  keys=['Base Color','Metallic','Roughness','IOR'];before={k:list(bs.inputs[k].default_value) if k=='Base Color' else bs.inputs[k].default_value for k in keys};bs.inputs['IOR'].default_value=1.5
  if variant=='functional_unlit':
   diffuser='::000' in m.name
   bs.inputs['Metallic'].default_value=0 if diffuser else 1
   bs.inputs['Roughness'].default_value=.4 if diffuser else .18
   bs.inputs['Base Color'].default_value=(.8,.8,.8,1) if diffuser else (.65,.65,.65,1)
  after={k:list(bs.inputs[k].default_value) if k=='Base Color' else bs.inputs[k].default_value for k in keys};changes.append({'material':m.name,'before':before,'after':after})
 assert len(changes)==2;used={s.material for o in bpy.context.scene.objects if o.type=='MESH' for s in o.material_slots};assert all(any(c['material']==m.name for c in changes) for m in used)
 bpy.ops.wm.save_as_mainfile(filepath=str(out));rows.append({'variant':variant,'source':str(S),'candidate':str(out),'changes':changes,'scope':'Same native geometry/UV/transforms/world/studio lights. No emission or photometric calibration. Functional profile based on named source MAT_SELFILL_SPOT vs Metal___Chrome_2017; material appearance requires actual A/B.'})
(D/'material_profile_controls.json').write_text(json.dumps({'controls':rows,'photorealism_accepted':False},indent=2)+'\n');print('LIGHT_PROFILE_CONTROLS_SAVED',flush=True)
