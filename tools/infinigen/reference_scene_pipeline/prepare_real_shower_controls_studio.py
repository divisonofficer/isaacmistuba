"""Pair real shower kit with a separately sourced thermostatic valve, before room fit."""
import bpy,json,hashlib,shutil,sys,math
from pathlib import Path
from mathutils import Matrix,Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from curated_gltf_materials import import_curated_gltf
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/real_shower_kit_candidate'
out=D/'with_controls';assert not out.exists();out.mkdir()
entry=next(e for e in json.loads((R/'vendor_datasets/hssd_objects/hssd_object_index.json').read_text())['objects']
           if e['id']=='HSSD_da563ad88ad4606e27514b55efb1032ccd9fa5b2')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
src=Path(entry['path']);local=R/'assets/opticalnav_curated/residential_real_shower_controls'/entry['id']
assert not local.exists();local.mkdir(parents=True);target=local/src.name
shutil.copyfile(src,target);assert sha(src)==sha(target)
dependencies=[]
for kind in ['buffers','images']:
    for item in json.loads(target.read_text()).get(kind,[]):
        uri=item.get('uri','')
        if not uri or uri.startswith('data:'):continue
        rel=Path(uri);assert not rel.is_absolute() and '..' not in rel.parts
        copied=local/rel;copied.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(src.parent/rel,copied);assert sha(src.parent/rel)==sha(copied)
        dependencies.append({'uri':uri,'sha256':sha(copied)})
entry={**entry,'path':str(target),'original_path':str(src),'copied_sha256':sha(target),
       'source_sha256':sha(src),'dependencies':dependencies}
# Known chrome control plate only: explicit authored polished response, not measured.
entry['mr_override']={m['name']:{'metallic':1.0,'roughness':.12}
                      for m in json.loads(target.read_text())['materials']}
entry['material_authoring']='Chrome valve: authored metallic1/roughness0.12 and invalidIOR repair1.5. Native geometry/UV preserved; not measured BRDF.'
studio=D/'neutral_reflection_variant/review_studio.blend';bpy.ops.wm.open_mainfile(filepath=str(studio))
kit_names=json.loads((D/'review_scope.json').read_text())['objects']
kit=[bpy.data.objects[n] for n in kit_names]
new,parts,profile=import_curated_gltf(entry,repair_nonpositive_ior=1.5)
world={o.name:o.matrix_world.copy() for o in parts}
for o in parts:o.parent=None;o.matrix_world=world[o.name]
for o in new:
    if o.type!='MESH':bpy.data.objects.remove(o,do_unlink=True)
def bounds(objects):
    points=[o.matrix_world@v.co for o in objects for v in o.data.vertices]
    return Vector(tuple(min(p[k] for p in points) for k in range(3))),Vector(tuple(max(p[k] for p in points) for k in range(3)))
lo,hi=bounds(parts);extent=hi-lo;axis=max(range(3),key=lambda k:extent[k])
rotation=Matrix.Identity(4)
if axis==1:rotation=Matrix.Rotation(math.pi/2,4,'X')
elif axis==0:rotation=Matrix.Rotation(-math.pi/2,4,'Y')
for o in parts:o.matrix_world=rotation@o.matrix_world
bpy.context.view_layer.update();lo,hi=bounds(parts);assert .18<hi.z-lo.z<.25
kit_lo,kit_hi=bounds(kit)
delta=Vector((.28-(lo.x+hi.x)/2,kit_hi.y-hi.y,.40-(lo.z+hi.z)/2))
for o in parts:o.location+=delta
bpy.context.view_layer.update()
for image in {n.image for o in parts for m in o.data.materials if m and m.use_nodes
              for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}:image.pack()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'review_studio.blend'))
(out/'review_views.json').write_text((D/'review_views.json').read_text())
(out/'valve_manifest.json').write_text(json.dumps(entry,indent=2))
(out/'review_scope.json').write_text(json.dumps({'kit_objects':kit_names,'valve_objects':[o.name for o in parts],
    'valve_faces':sum(len(o.data.polygons) for o in parts),'valve_material_profile':profile,
    'valve_translation':list(delta),'shared_rear_wall_plane_y':kit_hi.y,
    'scope':'Real kit plus actual two-way thermostatic controls, rigid local staging. Rear mounting envelope aligned; concealed plumbing and installed wall fit not certified. No room integration or photo approval.',
    'photorealism_accepted':False},indent=2))
print('REAL_SHOWER_CONTROLS_STUDIO_SAVED',flush=True)
