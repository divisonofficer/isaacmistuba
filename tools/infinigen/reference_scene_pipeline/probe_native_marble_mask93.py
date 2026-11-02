"""Actual wall-coordinate shader signal comparison, not a photographic material review."""
import bpy,json,numpy as np,hashlib
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
source=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r93.blend'
out=D/'native_marble_mask_probe_r93';assert not out.exists();out.mkdir()
bpy.ops.wm.open_mainfile(filepath=str(source));bpy.context.view_layer.update()
wall=bpy.data.objects['bathroom_0/2.wall'];original=wall.data.materials[0]
probe=bpy.data.scenes.new('NativeMarbleSignalProbe');probe.render.engine='CYCLES';probe.cycles.device='CPU'
probe.cycles.samples=16;probe.cycles.use_denoising=False;probe.render.threads_mode='FIXED';probe.render.threads=2
probe.render.resolution_x=probe.render.resolution_y=256;probe.render.resolution_percentage=100
probe.render.image_settings.file_format='OPEN_EXR';probe.render.image_settings.color_depth='32'
probe.view_settings.exposure=0;probe.view_settings.view_transform='Standard'
mesh=bpy.data.meshes.new('ActualWestWallCoordinatePatch');inv=wall.matrix_world.inverted()
mesh.from_pydata([inv@Vector(p) for p in [(.1145347,3.2,.12),(.1145347,5.8,.12),(.1145347,5.8,2.68),(.1145347,3.2,2.68)]],[],[(0,1,2,3)])
obj=bpy.data.objects.new(mesh.name,mesh);probe.collection.objects.link(obj);obj.matrix_world=wall.matrix_world.copy()
camera_data=bpy.data.cameras.new('MaskProbeCamera');camera=bpy.data.objects.new(camera_data.name,camera_data)
probe.collection.objects.link(camera);camera.location=(1.5,4.5,1.4)
camera.rotation_euler=(Vector((.1145347,4.5,1.4))-camera.location).to_track_quat('-Z','Y').to_euler()
camera_data.type='ORTHO';camera_data.ortho_scale=2.5;probe.camera=camera
rows=[]
for label,repair in [('A_native_scalar_vectors',False),('B_native_colour_vectors',True)]:
    mat=original.copy();changed=[]
    if repair:
        for node in mat.node_tree.nodes:
            if node.type not in ['TEX_NOISE','TEX_VORONOI'] or not node.inputs['Vector'].is_linked:continue
            link=node.inputs['Vector'].links[0]
            if link.from_node.type=='TEX_NOISE' and link.from_socket.name=='Fac':
                source_node=link.from_node;changed.append({'to':node.name,'from':source_node.name})
                mat.node_tree.links.new(source_node.outputs['Color'],node.inputs['Vector'])
        assert len(changed)==3
    mask=next(n for n in mat.node_tree.nodes if n.type=='MATH' and n.operation=='MULTIPLY')
    output=next(n for n in mat.node_tree.nodes if n.type=='OUTPUT_MATERIAL' and n.is_active_output)
    emission=mat.node_tree.nodes.new('ShaderNodeEmission');emission.inputs['Strength'].default_value=1
    mat.node_tree.links.new(mask.outputs[0],emission.inputs['Color']);mat.node_tree.links.new(emission.outputs[0],output.inputs['Surface'])
    mesh.materials.clear();mesh.materials.append(mat);path=out/(label+'.exr');probe.render.filepath=str(path)
    bpy.ops.render.render(write_still=True,scene=probe.name)
    image=bpy.data.images.load(str(path),check_existing=False);pixels=np.empty(len(image.pixels),np.float32)
    image.pixels.foreach_get(pixels);values=pixels.reshape(256,256,-1)[:,:,:3].mean(axis=2)
    rows.append({'case':label,'mean':float(values.mean()),'min':float(values.min()),'max':float(values.max()),
                 'std':float(values.std()),'fraction_above_0p05':float((values>.05).mean()),
                 'changed_vector_links':changed,'exr':str(path)})
    bpy.data.images.remove(image)
(out/'results.json').write_text(json.dumps({'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
    'rows':rows,'scope':'Emission-isolated native vein mask at actual west-wall local coordinates,256px/16spp,linearEXR. Not a room render or proof of realistic colour/roughness/normal. Original candidate unmodified.'},indent=2))
print('NATIVE_MARBLE_MASK_PROBE',json.dumps(rows),flush=True)
