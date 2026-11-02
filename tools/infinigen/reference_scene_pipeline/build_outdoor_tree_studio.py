"""Native-scale real outdoor assets under a diagnostic sky, no office edits."""
import bpy,json,hashlib,sys,math
from pathlib import Path
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).parent))
from curated_gltf_materials import import_curated_gltf
R=Path(__file__).resolve().parents[3]
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/outdoor_tree_candidates'
out=D/'review_studio.blend';assert not out.exists()
bpy.ops.wm.read_factory_settings(use_empty=True);rows=[];views=[]
for i,entry in enumerate(json.loads((D/'asset_manifest.json').read_text())['assets']):
    new,objects,profile=import_curated_gltf(entry)
    matrices={obj.name:obj.matrix_world.copy() for obj in objects}
    for obj in objects:obj.parent=None;obj.matrix_world=matrices[obj.name]
    for obj in new:
        if obj.type!='MESH':bpy.data.objects.remove(obj,do_unlink=True)
    bpy.context.view_layer.update()
    pts=[obj.matrix_world@Vector(v) for obj in objects for v in obj.bound_box]
    lo=Vector(tuple(min(v[k] for v in pts) for k in range(3)));hi=Vector(tuple(max(v[k] for v in pts) for k in range(3)))
    size=hi-lo;assert 3<size.z<6
    x=i*12;delta=Vector((x-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))
    for obj in objects:obj.location+=delta;obj['original_asset_id']=entry['id']
    center=Vector((x,0,size.z*.52));span=max(size.x,size.y,size.z*4/3)
    views.append({'name':entry['id']+'_native_scale','location':list(center+Vector((span*.7,-span*1.3,span*.28))),
        'target':list(center),'overview':True,'ortho_scale':span*1.4,'render_width':768,'samples':32})
    rows.append({'id':entry['id'],'source':entry['path'],'source_sha256':entry['source_sha256'],
        'objects':[o.name for o in objects],'native_extents_m':list(size),'translation_only_m':list(delta),
        'native_polygons':sum(len(o.data.polygons) for o in objects),'material_import_contract':profile})
for mat in bpy.data.materials:
    if mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type=='TEX_IMAGE' and node.image:
                assert min(node.image.size)>0;node.image.pack()
world=bpy.data.worlds.new('Diagnostic_outdoor_sky');world.use_nodes=True
sky=world.node_tree.nodes.new('ShaderNodeTexSky');sky.sky_type='NISHITA'
sky.sun_elevation=math.radians(38);sky.sun_rotation=math.radians(135)
bg=world.node_tree.nodes.get('Background');world.node_tree.links.new(sky.outputs['Color'],bg.inputs['Color'])
bg.inputs['Strength'].default_value=.3;bpy.context.scene.world=world
mat=bpy.data.materials.new('Diagnostic_ground_only');mat.use_nodes=True
bs=mat.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.12,.14,.10,1);bs.inputs['Roughness'].default_value=.85
mesh=bpy.data.meshes.new('Diagnostic_ground_only');mesh.from_pydata([(-8,-8,-.005),(20,-8,-.005),(20,8,-.005),(-8,8,-.005)],[],[(0,1,2,3)]);mesh.materials.append(mat)
obj=bpy.data.objects.new(mesh.name,mesh);bpy.context.scene.collection.objects.link(obj)
bpy.ops.wm.save_as_mainfile(filepath=str(out))
(D/'views.json').write_text(json.dumps(views,indent=2))
(D/'scope.json').write_text(json.dumps({'assets':rows,'source':str(out),'source_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
    'photorealism_accepted':False,'scope':'Actual project-local tree meshes,UV/PBR at native dimensions and only rigid translations. Diagnostic sky/ground, not an office exterior or reference match. Native alpha/leaf/shadow appearance requires actual images before integration.'},indent=2))
print('OUTDOOR_TREE_STUDIO_SAVED',flush=True)
