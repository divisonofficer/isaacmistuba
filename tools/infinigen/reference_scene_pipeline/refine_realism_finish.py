"""Correct active shader inputs and cylindrical brushed-metal coordinates."""
import argparse,bpy,json,hashlib,math
from pathlib import Path
from material_detail import material,noise,bump,range_value
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;old,rev=(20,21) if office else (25,26);base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}/full';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;source=base/f'scene_candidate_r{old}.blend';out=base/f'scene_candidate_r{rev}.blend';assert not out.exists();before=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));changes=[]
if office:
 o=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_machine_carafe');uv=o.data.uv_layers.new(name='CylindricalBrush')
 for poly in o.data.polygons:
  ids=list(poly.vertices)
  for li,vi in zip(poly.loop_indices,ids):
   k=vi%64;u=k/64
   if k==0 and any(j%64==63 for j in ids):u=1
   uv.data[li].uv=(u,(o.data.vertices[vi].co.z-min(v.co.z for v in o.data.vertices))/.10)
 m,n,l,bs,tc,geo=material('FineR2_cylindrical_brushed_stainless',(.55,.58,.62),.28,1);height=noise(n,l,tc.outputs['UV'],500,(1,.004,1));l.new(range_value(n,l,height,.25,.31),bs.inputs['Roughness']);l.new(bump(n,l,height,.000003,.10),bs.inputs['Normal']);bs.inputs['Anisotropic'].default_value=.4;bs.inputs['Anisotropic Rotation'].default_value=.25;m['reference_pbr_kind']='bare_metal';o.data.materials.clear();o.data.materials.append(m)
 for obj in bpy.data.objects:
  key=obj.get('program_key','')
  if key.startswith('machine_') or key=='coffee_machine':
   for modifier in obj.modifiers:
    if modifier.type=='BEVEL':modifier.width=min(modifier.width,.0012)
  if key=='machine_button':
   mod=obj.modifiers.new('control_edge_radius','BEVEL');mod.width=.0003;mod.segments=3
 # Physical diffuser/channel beneath the existing upper cabinetry.
 upper=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_upper');z=min((upper.matrix_world@__import__('mathutils').Vector(c)).z for c in upper.bound_box)
 lens,n,l,bs,tc,geo=material('FineR2_LED_diffuser',(.72,.70,.64),.35);bs.inputs['Emission Color'].default_value=(1,.94,.84,1);bs.inputs['Emission Strength'].default_value=2
 bpy.ops.mesh.primitive_cube_add(size=1,location=(14.42,5.15,z-.009));strip=bpy.context.object;strip.name='FineR2_under_cabinet_diffuser';strip.dimensions=(.035,3.25,.006);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);strip.data.materials.append(lens);strip['reference_scene_owner']=scene;strip['program_key']='under_cabinet_diffuser';strip['audit_kind']='fixture'
 changes=['Replaced triplanar scan on cylindrical pitcher with cylindrical-UV directional brush and3micrometre normal, avoiding foil-like distortion.','Reduced case/control edge radii and added mounted diffuser mesh.']
else:
 for m in bpy.data.materials:
  if m.get('reference_pbr_kind')!='glazed_ceramic':continue
  bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');socket=bs.inputs['Base Color'];node=socket.links[0].from_node if socket.is_linked else None
  if node and node.type=='MIX_RGB' and not node.inputs[1].is_linked:node.inputs[1].default_value=(.72,.715,.70,1);changes.append({'material':m.name,'active_base_color_constant':[.72,.715,.70]})
  elif not socket.is_linked:socket.default_value=(.72,.715,.70,1)
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==before;(ref/f'realism_refinement_r{rev}.json').write_text(json.dumps({'source':str(source),'source_sha256':before,'candidate':str(out),'changes':changes,'photorealism_accepted':False},indent=2));print(json.dumps({'saved':str(out),'changes':changes}),flush=True)
