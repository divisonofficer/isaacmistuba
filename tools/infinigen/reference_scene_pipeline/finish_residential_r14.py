"""Scan-normal textile projection, supported plants, and complementary review cameras."""
import bpy,json,math
from pathlib import Path
from mathutils import Vector,Matrix
from material_detail import triplanar_normal,scan,range_value
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r13.blend'))
textiles=json.loads((ref/'material_detail_r12.json').read_text())['textiles'];changed=[]
for m in bpy.data.materials:
 if m.name not in textiles and not m.name.startswith('ir_bal_teal'):continue
 n=m.node_tree.nodes;l=m.node_tree.links;bs=next(x for x in n if x.type=='BSDF_PRINCIPLED');geo=n.new('ShaderNodeNewGeometry')
 l.new(triplanar_normal(n,l,ref/'pbr_assets','fabric_0022',geo.outputs['Position'],geo.outputs['Normal'],3,.55),bs.inputs['Normal']);m['reference_pbr_kind']='textile'
 if m.name.startswith('ir_bal_teal'):
  bs.inputs['Base Color'].default_value=(.28,.32,.29,1);mp=n.new('ShaderNodeVectorMath');mp.operation='SCALE';mp.inputs[3].default_value=3;l.new(geo.outputs['Position'],mp.inputs[0]);r=scan(n,l,ref/'pbr_assets','fabric_0022','roughness.jpg',mp.outputs[0]);l.new(range_value(n,l,r,.68,.95),bs.inputs['Roughness']);bs.inputs['Sheen Weight'].default_value=.25
 changed.append(m.name)
# Reuse a proven native plant, hollow pot and soil assembly together. Scale and
# translate the entire group in world coordinates, retaining real root support.
source=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r15.blend'
with bpy.data.libraries.load(str(source),link=False) as (src,dst):
 names=['Office02_native_plant_0','Office02_r6_pot_0','Office02_r6_soil_0'];assert all(x in src.objects for x in names);dst.objects=names
protos=dst.objects
for o in protos:bpy.context.scene.collection.objects.link(o)
plant=protos[0];pot=protos[1];bpy.context.view_layer.update();pts=[pot.matrix_world@Vector(c) for c in pot.bound_box];oldfz=min(v.z for v in pts);pivot=Vector((plant.location.x,plant.location.y,oldfz))
floor=bpy.data.objects['bedroom_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box)
added=[]
for index,(x,y) in enumerate([(6.0,8.55),(.65,17.35),(4.35,17.35),(15.5,8.55),(20.85,17.35),(17.15,17.35)]):
 transform=Matrix.Translation(Vector((x,y,fz)))@Matrix.Scale(.75,4)@Matrix.Translation(-pivot)
 for prototype,key,kind in zip(protos,['plant','pot','soil'],['vegetation','ground_container','soil']):
  o=prototype.copy();o.data=prototype.data.copy();bpy.context.scene.collection.objects.link(o);o.matrix_world=transform@prototype.matrix_world
  o.name=f'Residential03_r14_{key}_{index}';o['reference_scene_owner']='dual_unit_residential_floor_03';o['program_key']=f'{key}_{index}';o['audit_kind']=kind;added.append(o.name)
for o in protos:bpy.data.objects.remove(o,do_unlink=True)
views=json.loads((base/'review_views_r9.json').read_text())
views += [{'name':'shared_corridor_context','location':[11.75,1.05,1.55],'target':[11.75,6.2,1.5],'hfov':80},{'name':'elevator_context','location':[12.1,4.8,1.55],'target':[11.02,3.6,1.25],'hfov':85}]
for unit in (101,102):
 mirror=lambda p:[21.5-p[0],p[1],p[2]] if unit==102 else p
 for name,location,target,hfov in [('dressing_context',[4.45,14.1,1.55],[3.1,12.5,1.3],85),('bathroom_wc_reverse',[.4,5.5,1.55],[2.2,3.8,1.0],80),('sofa_material_close',[2.15,7.1,1.0],[.98,7.65,.62],50)]:
  views.append({'name':f'{unit}_{name}','location':mirror(location),'target':mirror(target),'hfov':hfov})
(base/'review_views_r14.json').write_text(json.dumps(views,indent=2))
out=base/'scene_candidate_r14.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'material_detail_r14.json').write_text(json.dumps({'source':'scene_candidate_r13.blend','scan_normal_textiles':changed,'normal_projection':'World-axis planar perturbations, no assumed factory UV tangents','supported_native_plant_assemblies':6,'new_review_views':8,'visual_acceptance':False},indent=2))
