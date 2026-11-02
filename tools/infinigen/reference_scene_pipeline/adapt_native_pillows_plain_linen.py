"""Plain reference palette on native curved pillows; retain source UV/normal/ORM."""
import bpy,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/real_pillow_candidates';out=D/'plain_linen_studio.blend';assert not out.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();source=D/'review_studio.blend';before=sha(source);meta=json.loads((D/'scope.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(source));records=[]
for row,color in zip(meta['objects'],[(.46,.42,.34,1),(.18,.23,.16,1)]):
 o=bpy.data.objects[row['object']];m=o.data.materials[0].copy();o.data.materials[0]=m;m.name='Authored_plain_linen_'+o.name;n,l=m.node_tree.nodes,m.node_tree.links;bs=next(x for x in n if x.type=='BSDF_PRINCIPLED');old=bs.inputs['Base Color'].links[0].from_node.name
 for link in list(bs.inputs['Base Color'].links):l.remove(link)
 # Tiny colour variation only; native scanned weave normal and ORM remain active.
 geo=n.new('ShaderNodeNewGeometry');noise=n.new('ShaderNodeTexNoise');noise.name='Authored_linen_soft_colour';noise.inputs['Scale'].default_value=35;noise.inputs['Detail'].default_value=2;l.new(geo.outputs['Position'],noise.inputs['Vector'])
 ramp=n.new('ShaderNodeValToRGB');ramp.name='Authored_linen_palette';ramp.color_ramp.elements[0].color=tuple(v*.985 for v in color[:3])+(1,);ramp.color_ramp.elements[1].color=tuple(v*1.015 for v in color[:3])+(1,);l.new(noise.outputs['Fac'],ramp.inputs[0]);l.new(ramp.outputs['Color'],bs.inputs['Base Color'])
 before_inputs={k:float(bs.inputs[k].default_value) for k in ['Metallic','IOR','Coat Weight','Sheen Weight']};bs.inputs['IOR'].default_value=1.46;bs.inputs['Coat Weight'].default_value=0;bs.inputs['Sheen Weight'].default_value=.15
 assert bs.inputs['Normal'].is_linked and bs.inputs['Roughness'].is_linked and bs.inputs['Metallic'].is_linked
 records.append({'object':o.name,'material':m.name,'before_inputs':before_inputs,'replaced_basecolor_source':old,'authored_colour_linear':list(color),'native_normal_orm_uv_preserved':True})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert sha(source)==before
(D/'plain_linen_scope.json').write_text(json.dumps({'source':str(source),'source_sha256':before,'candidate':str(out),'candidate_sha256':sha(out),'records':records,'change':'Only authored plain warm/sage BaseColor,IOR1.46,Coat0,Sheen.15. Native shape,UV,weave normal and ORM retained; printed zigzag colour not used. No scanned-plain-linen or measuredBRDF claim.','photorealism_accepted':False},indent=2))
