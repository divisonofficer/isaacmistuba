"""Timber grain follows member length; retain scan colour detail and separate cut-end response."""
import bpy,json,hashlib,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r48.blend';out=base/'scene_candidate_r49.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));source_material=next(o for o in bpy.data.objects if '_continuous_rear_stile_' in o.get('program_key','')).data.materials[0];m=source_material.copy();m.name='R49_lengthwise_scan_oak';n=m.node_tree.nodes;l=m.node_tree.links;bs=next(n for n in n if n.type=='BSDF_PRINCIPLED');image=next(n for n in n if n.type=='TEX_IMAGE' and n.image and 'base_color' in n.image.filepath);assert image.projection=='FLAT';before={}
for node in n:
 if node.type=='MAP_RANGE':before[node.name]=[{'index':i,'identifier':s.identifier,'name':s.name,'type':s.type,'value':list(s.default_value) if hasattr(s.default_value,'__len__') else s.default_value} for i,s in enumerate(node.inputs) if hasattr(s,'default_value')]
# Measured source image linear RGB mean,512px sample; calibrated near the old mean appearance.
mean=(.4266959074,.2263774732,.1054940393);target=(.428,.303,.178);gain=tuple(t/s for t,s in zip(target,mean));multiply=n.new('ShaderNodeVectorMath');multiply.operation='MULTIPLY';multiply.label='Preserve scan colour with calibrated mean';multiply.inputs[1].default_value=gain;l.new(image.outputs['Color'],multiply.inputs[0]);l.new(multiply.outputs[0],bs.inputs['Base Color']);m['reference_pbr_kind']='wood'
end=bpy.data.materials.new('R49_oak_cut_end');end.use_nodes=True;en=end.node_tree.nodes;el=end.node_tree.links;eb=en.get('Principled BSDF');eb.inputs['Roughness'].default_value=.44;eb.inputs['Coat Weight'].default_value=.12;eb.inputs['Coat Roughness'].default_value=.28;tc=en.new('ShaderNodeTexCoord');offset=en.new('ShaderNodeVectorMath');offset.operation='ADD';offset.inputs[1].default_value=(3,2,0);el.new(tc.outputs['UV'],offset.inputs[0]);wave=en.new('ShaderNodeTexWave');wave.wave_type='RINGS';wave.rings_direction='Z';wave.inputs['Scale'].default_value=6;wave.inputs['Distortion'].default_value=1.5;wave.inputs['Detail'].default_value=2;wave.inputs['Detail Scale'].default_value=1.3;el.new(offset.outputs[0],wave.inputs['Vector']);ramp=en.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(.35,.235,.13,1);ramp.color_ramp.elements[1].color=(.43,.295,.17,1);el.new(wave.outputs['Fac'],ramp.inputs[0]);el.new(ramp.outputs[0],eb.inputs['Base Color']);bump=en.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.000015;el.new(wave.outputs['Fac'],bump.inputs['Height']);el.new(bump.outputs[0],eb.inputs['Normal']);end['reference_pbr_kind']='wood_endgrain';rows=[]
for o in bpy.data.objects:
 key=o.get('program_key','')
 if o.type!='MESH' or not key.startswith('breakout_chair'):continue
 indices=[i for i,mat in enumerate(o.data.materials) if mat==source_material]
 if not indices:continue
 o.data=o.data.copy();uv=o.data.uv_layers.active;assert uv is not None,(o.name,'missingUV');targetfaces=[f for f in o.data.polygons if f.material_index in indices];loops={li for f in targetfaces for li in f.loop_indices}
 for li in loops:u,v=uv.data[li].uv;uv.data[li].uv=(v,u)
 for i in indices:o.data.materials[i]=m
 capindex=len(o.data.materials);o.data.materials.append(end);capcount=0
 for f in targetfaces:
  isapron=key.endswith('_rear_apron');isend=abs(f.normal.y)>.99 if isapron else abs(f.normal.z)>.99
  if not isend:continue
  f.material_index=capindex;capcount+=1;points=[o.data.vertices[i].co for i in f.vertices];axis=(0,2) if isapron else (0,1);center=[sum(p[a] for p in points)/len(points) for a in axis]
  for li in f.loop_indices:
   q=o.data.vertices[o.data.loops[li].vertex_index].co;uv.data[li].uv=((q[axis[0]]-center[0])/.032+.5,(q[axis[1]]-center[1])/.032+.5)
 o.data.update();rows.append({'object':o.name,'wood_faces':len(targetfaces),'end_faces':capcount,'UV_change':'swap scan axes:horizontal source grain along member length','geometry':'unchanged'})
assert len(rows)==16,(len(rows),rows);bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r49.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'scope':'chair timber material/UV only;all geometry,metal,textile,camera andlighting unchanged','source_image_linear_mean':mean,'target_mean_linear':target,'rgb_gain':gain,'previous_map_range_indexed_inputs':before,'side_scan':'pbr_assets/wood_0002/base_color.jpg','cut_end':'separate procedural off-centre ring field,not a scanned endgrain asset','objects':rows,'photorealism_accepted':False,'requires':'same front/rear actual renders;check for ring banding,wood scale,colour/material regression before adoption'},indent=2));print('SAVED',out,flush=True)
