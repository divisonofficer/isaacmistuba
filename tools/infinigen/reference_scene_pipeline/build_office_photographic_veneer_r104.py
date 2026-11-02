"""Photographic oak PBR on actual cabinet panels with explicit metric UVs."""
import bpy,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';B=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';S=B/'scene_candidate_r102.blend';O=B/'scene_candidate_r104.blend';assert not O.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();hs=sha(S);A=D/'pbr_assets/polyhaven_oak_veneer_03';prov=json.loads((A/'provenance.json').read_text())
for f in prov['files']:assert sha(R/f['path'])==f['sha256']
bpy.ops.wm.open_mainfile(filepath=str(S));mat=bpy.data.materials.new('Office02_r104_photographic_sealed_oak');mat.use_nodes=True;n,l=mat.node_tree.nodes,mat.node_tree.links;bs=n.get('Principled BSDF');bs.inputs['Metallic'].default_value=0;bs.inputs['IOR'].default_value=1.5;bs.inputs['Coat Weight'].default_value=.15;bs.inputs['Coat Roughness'].default_value=.20
uv=n.new('ShaderNodeUVMap');uv.uv_map='R104_veneer_metres';images={}
for f in prov['files']:
 im=bpy.data.images.load(str(R/f['path']),check_existing=True);im.colorspace_settings.name='sRGB' if f['role']=='diff' else 'Non-Color';im.pack();tex=n.new('ShaderNodeTexImage');tex.name='R104_'+f['role'];tex.image=im;tex.projection='FLAT';tex.extension='REPEAT';l.new(uv.outputs[0],tex.inputs['Vector']);images[f['role']]=tex
mix=n.new('ShaderNodeMixRGB');mix.name='R104_preserved_linear_gain';mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1;mix.inputs[2].default_value=(.68,.68,.68,1);l.new(images['diff'].outputs['Color'],mix.inputs[1]);l.new(mix.outputs[0],bs.inputs['Base Color']);l.new(images['rough'].outputs['Color'],bs.inputs['Roughness']);normal=n.new('ShaderNodeNormalMap');normal.name='R104_native_GL_normal';normal.uv_map='R104_veneer_metres';normal.inputs['Strength'].default_value=1;l.new(images['nor_gl'].outputs['Color'],normal.inputs['Color']);l.new(normal.outputs[0],bs.inputs['Normal']);mat['reference_pbr_kind']='wood';mat['asset_provenance']='https://polyhaven.com/a/oak_veneer_03'
rows=[]
for i,o in enumerate(sorted(bpy.context.scene.objects,key=lambda x:x.name)):
 if o.type!='MESH' or o.get('program_key') not in ['coffee_cabinet_front','coffee_upper_front']:continue
 assert len(o.data.materials)==1,(o.name,len(o.data.materials));old=[m.name for m in o.data.materials];o.data=o.data.copy();mesh=o.data;geom=hashlib.sha256(repr(([tuple(v.co) for v in mesh.vertices],[tuple(f.vertices) for f in mesh.polygons])).encode()).hexdigest();active=mesh.uv_layers.active_index;layer=mesh.uv_layers.new(name='R104_veneer_metres');phase=(i*.271)%1
 for f in mesh.polygons:
  nn=(o.matrix_world.to_3x3().inverted().transposed()@f.normal).normalized()
  for li in f.loop_indices:
   p=o.matrix_world@mesh.vertices[mesh.loops[li].vertex_index].co
   layer.data[li].uv=(p.z+phase,p.y) if abs(nn.x)>.5 else ((p.z+phase,p.x) if abs(nn.y)>.5 else (p.y+phase,p.x))
 mesh.uv_layers.active_index=active;mesh.materials.clear();mesh.materials.append(mat)
 for f in mesh.polygons:f.material_index=0
 rows.append({'object':o.name,'old_materials':old,'geometry_sha256':geom,'uv_layer':'R104_veneer_metres','phase_m':phase,'material':mat.name})
assert len(rows)==11,len(rows);bpy.ops.wm.save_as_mainfile(filepath=str(O));assert sha(S)==hs
meta=json.loads((D/'realism_refinement_r102.json').read_text());meta.update(source=str(S),source_sha256=hs,candidate=str(O),candidate_sha256=sha(O),change='Only11breakout cabinet wood fronts: photographic oak03 diffuse/roughness/GLnormal4K,exact metric vertical-grainUV1m/texture,authored sealed coat. Shape/modifiers/other materials/world/lights/cameras preserved. No exterior103changes.',photographic_veneer={'provenance':str(A/'provenance.json'),'files':prov['files'],'objects':rows,'material':mat.name,'linear_basecolor_gain':.68,'coat_weight':.15,'coat_roughness':.2,'native_normal_strength':1,'scope':'Native photographic PBR maps,not measuredBRDF;authored sealer. Old gain retained,roughness now uses source data directly. Only11doors,not filler/all wood/floor. Physical grain scale from worldmetreUV,not existing arbitrary local-unitUV. Visual/reference and saved-source gates pending.'},photorealism_accepted=False);(D/'realism_refinement_r104.json').write_text(json.dumps(meta,indent=2))
