"""Photo-oak physical-scale finish trial on existing desk/table/storage surfaces; no geometry claim."""
import bpy,json,sys,hashlib
from pathlib import Path
from mathutils import Vector
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from compact_wc_contract import mesh_geometry_hash
from curated_gltf_materials import preserve_native_packed_image
D=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';base=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';src=base/'scene_candidate_r114_draft.blend';dst=base/'scene_candidate_r115_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();source_hash=sha(src);root=D/'pbr_assets/polyhaven_oak_veneer_03';provenance=json.loads((root/'provenance.json').read_text())
for f in provenance['files']:assert sha(r/f['path'])==f['sha256']
bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();before={o.name:{'matrix':[list(v) for v in o.matrix_world],'geometry':mesh_geometry_hash(o.data) if o.type=='MESH' else None} for o in bpy.context.scene.objects};mat=bpy.data.materials.new('Office115_photographic_oak_metres');mat.use_nodes=True;n=mat.node_tree.nodes;l=mat.node_tree.links;bs=n.get('Principled BSDF');uv=n.new('ShaderNodeUVMap');uv.uv_map='Office115_oak_metres';textures={}
for role,suffix,color in [('color','diff_4k.jpg',True),('roughness','rough_4k.jpg',False),('normal','nor_gl_4k.png',False)]:
 im=bpy.data.images.load(str(root/('oak_veneer_03_'+suffix)),check_existing=True);im.colorspace_settings.name='sRGB' if color else 'Non-Color';tx=n.new('ShaderNodeTexImage');tx.image=im;tx.extension='REPEAT';l.new(uv.outputs[0],tx.inputs['Vector']);textures[role]=tx
l.new(textures['color'].outputs['Color'],bs.inputs['Base Color']);l.new(textures['roughness'].outputs['Color'],bs.inputs['Roughness']);normal=n.new('ShaderNodeNormalMap');normal.space='TANGENT';normal.uv_map=uv.uv_map;normal.inputs['Strength'].default_value=1;l.new(textures['normal'].outputs['Color'],normal.inputs['Color']);l.new(normal.outputs[0],bs.inputs['Normal']);bs.inputs['Metallic'].default_value=0;bs.inputs['IOR'].default_value=1.5;bs.inputs['Coat Weight'].default_value=.2;bs.inputs['Coat Roughness'].default_value=.2;rows=[]
allowed={'office02_reference_warm_oak','ir_desk_panel_oak','ir_pedestal_oak','ir_cred_oak','ir_cred_oak2'}
for o in bpy.context.scene.objects:
 if o.type!='MESH':continue
 key=str(o.get('program_key',''));is_target=key.startswith(('private_','pod_')) or key in ['conference_a_table','meeting_b_table','meeting_c_table','conference_a_credenza','meeting_b_credenza','meeting_c_credenza']
 if not is_target:continue
 slots={i:m.name for i,m in enumerate(o.data.materials) if m and m.name in allowed};faces=[f.index for f in o.data.polygons if f.material_index in slots]
 if not faces:continue
 o.data=o.data.copy();me=o.data;prior_active=me.uv_layers.active_index;layer=me.uv_layers.new(name=uv.uv_map);scales=[o.matrix_world.col[i].to_3d().length for i in range(3)];phase=int(hashlib.sha256(o.name.encode()).hexdigest()[:8],16)/2**32
 for fi in faces:
  face=me.polygons[fi];coords=[me.vertices[v].co for v in face.vertices];dims=[(max(p[k] for p in coords)-min(p[k] for p in coords))*scales[k] for k in range(3)];axes=sorted(range(3),key=lambda k:dims[k],reverse=True);u,v=axes[:2]
  # Longest actual face direction carries grain; dimensions are metres, no object-normalized scaling.
  for li in face.loop_indices:
   p=me.vertices[me.loops[li].vertex_index].co;layer.data[li].uv=(p[u]*scales[u]+phase,p[v]*scales[v])
 me.uv_layers.active_index=prior_active
 for i in slots:me.materials[i]=mat
 assert mesh_geometry_hash(me)==before[o.name]['geometry'];rows.append({'object':o.name,'program_key':key,'replaced_slots':slots,'faces':len(faces),'uv_layer':uv.uv_map,'existing_active_uv_preserved':True,'grain_mapping':'Each actual raw face longest in-plane metric extent as U; metre-valued local coordinates scaled by world basis lengths, stable per-object phase. Not a manufacturing panel joinery reconstruction.','geometry_unchanged':True})
assert rows
for o in bpy.context.scene.objects:
 assert before[o.name]['matrix']==[list(v) for v in o.matrix_world]
 if o.type=='MESH':assert before[o.name]['geometry']==mesh_geometry_hash(o.data)
packed=[preserve_native_packed_image(tx.image) for tx in textures.values()];bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==source_hash
(D/'wood115_build.json').write_text(json.dumps({'source':str(src),'source_sha256':source_hash,'candidate':str(dst),'candidate_sha256':sha(dst),'rows':rows,'provenance':provenance,'packed_images':packed,'all_raw_geometry_and_object_matrices_unchanged':True,'scope':'Photographic finish / per-face metric UV trial only. No noise/tint/exposure/light/geometry change. Existing primitive or incomplete furniture construction remains open; no stand-in asset introduced and no claim of manufacturing improvement. Existing105 photographic coffee cabinetry, all floors/doors and nonwood slots retained. Direct same-camera RGB and independent reference review required.','accepted':False},indent=2));print('OFFICE115_SAVED',len(rows),flush=True)
