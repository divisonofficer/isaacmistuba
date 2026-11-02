import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];W=R/'out/infinigen_v2/kr_large_restaurant_floor_07_48712507';out=W/'furnished_r4_materials.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(W/'furnished_r4.blend'));rows=[]
# Exact source material001 is labelled mig_00wood geometry; glTF omitted metallicFactor and defaulted to1.
for m in bpy.data.materials:
 if '8ca311f2d9dfe726d268e0386285d1a6ac466848::001' not in m.name or not m.use_nodes:continue
 for b in [n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED']:
  assert not b.inputs['Metallic'].is_linked and not b.inputs['Roughness'].is_linked;before={k:float(b.inputs[k].default_value) for k in ['Metallic','Roughness','IOR']};b.inputs['Metallic'].default_value=0;b.inputs['Roughness'].default_value=.55;b.inputs['IOR'].default_value=1.5;rows.append({'material':m.name,'before':before,'after':{'Metallic':0,'Roughness':.55,'IOR':1.5},'authority':'Explicit inferred dielectric reclaimed wood classification; not measured optical data. Native basecolor/normal maps and bitmap bytes unchanged.'})
assert rows,'Exact wood material profile missing';bpy.ops.wm.save_as_mainfile(filepath=str(out));(W/'dining_material_profile_r4.json').write_text(json.dumps({'changes':rows,'photorealism_accepted':False},indent=2));inv=json.loads((W/'native_product_inventory_r4.json').read_text());inv['scope']+=' Exact source reclaimed wood material001 glTF metallic default1 corrected to inferred dielectric0,roughness0.55,IOR1.5;linked native metal ORM unchanged.';(W/'native_product_inventory_r4_materials.json').write_text(json.dumps(inv,indent=2));(W/'furnished_r4_materials_views.json').write_text((W/'furnished_r4_views.json').read_text());print('DINING_MATERIAL_PROFILE_SAVED',rows,flush=True)
