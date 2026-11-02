"""Real five-part bed regression: missing profiles reject; repaired import passes."""
import bpy,json,sys,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from curated_gltf_materials import inspect_hssd_profile,apply_hssd_profile,import_curated_gltf
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';O=D/'hssd_profile_import_regression.json';assert not O.exists();entry=next(e for e in json.loads((D/'real_bed_candidates/asset_candidates_manifest.json').read_text())['assets'] if '7f6e6db8a0b89d1f055e46dec741245cb390c1ab' in e['id']);bpy.ops.wm.read_factory_settings(use_empty=True);src=R/entry['path'];bpy.ops.import_scene.gltf(filepath=str(src));objects=[o for o in bpy.context.scene.objects if o.type=='MESH'];assert len(objects)==5
def fingerprint(objs):
 rows=[]
 for o in objs:
  rows.append({'name':o.name,'vertices':[list(v.co) for v in o.data.vertices],'polygons':[list(f.vertices) for f in o.data.polygons],'uv':[[list(v.uv) for v in layer.data] for layer in o.data.uv_layers],'matrix':[list(v) for v in o.matrix_world]})
 return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
def image_bindings(objs):
 return sorted((n.image.filepath,n.image.name,n.image.colorspace_settings.name) for m in {m for o in objs for m in o.data.materials if m and m.use_nodes} for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image)
before=fingerprint(objects);images=image_bindings(objects);negative=inspect_hssd_profile(objects,entry);assert not negative['pass'] and len(negative['errors'])==15,negative
positive=apply_hssd_profile(objects,entry,repair_nonpositive_ior=1.5);assert positive['pass'] and len(positive['changes'])==5;assert fingerprint(objects)==before and image_bindings(objects)==images
bpy.ops.wm.read_factory_settings(use_empty=True);new,objects,imported=import_curated_gltf(entry,repair_nonpositive_ior=1.5);assert imported['pass'] and len(objects)==5
O.write_text(json.dumps({'asset_id':entry['id'],'negative_before_override':negative,'positive_after_override':positive,'verified_import_api':imported,'geometry_uv_transform_fingerprint_unchanged':before,'image_bindings_unchanged':True,'source_files_or_scene_candidates_modified':False,'scope':'Actual native5part bed import regression,not toy data. Does not approve appearance,measuredBRDF or other asset families.','photorealism_accepted':False},indent=2)+'\n');print('HSSD_PROFILE_IMPORT_REGRESSION_PASSED',flush=True)
