"""Actual 12k-face shower assembly, local dependencies and explicit shader provenance."""
import bpy,json,hashlib,shutil,sys,math
from pathlib import Path
from mathutils import Matrix,Vector
R=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(Path(__file__).parent))
from curated_gltf_materials import import_curated_gltf
index=R/'vendor_datasets/hssd_objects/hssd_object_index.json'
entry=next(e for e in json.loads(index.read_text())['objects']
           if e['id']=='HSSD_9e068412c7ca15a5d23c5813614150ff138d9bb6')
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/real_shower_kit_candidate'
assert not D.exists();D.mkdir()
local=R/'assets/opticalnav_curated/residential_real_shower_kit'/entry['id']
assert not local.exists();local.mkdir(parents=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
original=Path(entry['path']);target=local/original.name
shutil.copyfile(original,target);assert sha(original)==sha(target)
doc=json.loads(target.read_text());dependencies=[]
for kind in ['buffers','images']:
    for item in doc.get(kind,[]):
        uri=item.get('uri','')
        if not uri or uri.startswith('data:'):continue
        path=Path(uri);assert not path.is_absolute() and '..' not in path.parts
        src=original.parent/path;dst=local/path;dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src,dst);assert sha(src)==sha(dst)
        dependencies.append({'uri':uri,'sha256':sha(dst)})
entry={**entry,'original_path':str(original),'original_index':str(index),
       'path':str(target),'copied_sha256':sha(target),'source_sha256':sha(original),
       'dependencies':dependencies,'visual_acceptance':False}
# Explicit authoring choices for the TWO known chrome slots, not a global IOR rule.
entry['mr_override']=dict(entry['mr_override'])
for suffix in ['000','003']:
    entry['mr_override'][f'HSSD_MAT::9e068412c7ca15a5d23c5813614150ff138d9bb6::{suffix}']={
        'metallic':1.0,'roughness':.12}
entry['chrome_authoring']='Slots000/003 source metallic1/roughness0 -> authored roughness0.12; invalid IOR repaired1.5 explicitly. Other declared registry profiles retained; native003 normal map preserved. Not measured BRDF.'
bpy.ops.wm.read_factory_settings(use_empty=True)
new,objects,profile=import_curated_gltf(entry,repair_nonpositive_ior=1.5)
matrices={o.name:o.matrix_world.copy() for o in objects}
for o in objects:o.parent=None;o.matrix_world=matrices[o.name]
for o in new:
    if o.type!='MESH':bpy.data.objects.remove(o,do_unlink=True)
def bounds():
    points=[o.matrix_world@v.co for o in objects for v in o.data.vertices]
    return Vector(tuple(min(p[k] for p in points) for k in range(3))),Vector(tuple(max(p[k] for p in points) for k in range(3)))
lo,hi=bounds();extent=hi-lo;axis=max(range(3),key=lambda k:extent[k])
orientation=Matrix.Identity(4)
if axis==1:orientation=Matrix.Rotation(math.pi/2,4,'X')
elif axis==0:orientation=Matrix.Rotation(-math.pi/2,4,'Y')
for o in objects:o.matrix_world=orientation@o.matrix_world
bpy.context.view_layer.update();lo,hi=bounds();extent=hi-lo
assert 1.3<extent.z<1.7
delta=Vector((-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))
for o in objects:o.location+=delta
images=[]
used={n.image for o in objects for m in o.data.materials if m and m.use_nodes
      for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}
for image in used:
    image.pack();assert image.packed_file
    images.append({'name':image.name,'packed_sha256':hashlib.sha256(image.packed_file.data).hexdigest()})
views=[{'name':'shower_whole_front','location':[1.8,-3.1,1.9],'target':[0,0,.75],
        'overview':True,'ortho_scale':2.05,'render_width':768,'samples':48},
       {'name':'shower_whole_reverse','location':[-1.8,3.1,1.9],'target':[0,0,.75],
        'overview':True,'ortho_scale':2.05,'render_width':768,'samples':48}]
target_point=Vector((0,0,.75))
for i,(offset,power,size) in enumerate([((0,-2,3),180,1.5),((2,1,2),100,1.2)]):
    data=bpy.data.lights.new(f'ShowerStudio_{i}','AREA');data.energy=power;data.shape='DISK';data.size=size
    obj=bpy.data.objects.new(data.name,data);bpy.context.scene.collection.objects.link(obj)
    obj.location=offset;obj.rotation_euler=(target_point-obj.location).to_track_quat('-Z','Y').to_euler()
world=bpy.data.worlds.new('Neutral_Shower_Studio');world.use_nodes=True
world.node_tree.nodes['Background'].inputs['Strength'].default_value=.12;bpy.context.scene.world=world
bpy.ops.wm.save_as_mainfile(filepath=str(D/'review_studio.blend'))
(D/'review_views.json').write_text(json.dumps(views,indent=2))
(D/'asset_manifest.json').write_text(json.dumps(entry,indent=2))
(D/'review_scope.json').write_text(json.dumps({'objects':[o.name for o in objects],
    'actual_polygons':sum(len(o.data.polygons) for o in objects),
    'upright_extent_m':list(extent),'native_long_axis':axis,
    'rigid_orientation_matrix':[list(r) for r in orientation],'translation_only':list(delta),
    'material_profile':profile,'packed_images':images,'photorealism_accepted':False,
    'scope':'Actual source assembly, no stand-in meshes, rigid upright staging and explicitly authored chrome roughness/IOR. Whole front/reverse visual checks required before room placement.'},indent=2))
print('REAL_SHOWER_KIT_STUDIO_SAVED',flush=True)
