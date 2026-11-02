"""Bounded saved-source exterior surface checks; RGB/reference review remains required."""
import bpy,json,hashlib,sys,argparse
from pathlib import Path
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--revision',required=True,type=int)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
m=json.loads((D/f'realism_refinement_r{a.revision}.json').read_text());e=m['east_photo']
out=D/f'east_photo_saved_audit_r{a.revision}.json';assert not out.exists()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(m['candidate'])==m['candidate_sha256'] and sha(m['source'])==m['source_sha256']
bpy.ops.wm.open_mainfile(filepath=m['candidate'])
east=bpy.data.objects[e['object']];west=bpy.data.objects[e['source_object']]
points=[east.matrix_world@v.co for v in east.data.vertices]
flags=['visible_camera','visible_diffuse','visible_glossy','visible_transmission','visible_shadow']
checks={'east_plane_x66p5m':all(abs(v.x-66.5)<1e-3 for v in points),
    'native_quad_and_uv':len(east.data.polygons)==1 and len(east.data.vertices)==4 and len(east.data.uv_layers)>0,
    'local_geometry_preserved':list(v.co[:] for v in east.data.vertices)==list(v.co[:] for v in west.data.vertices),
    'uv_preserved':list(v.uv[:] for v in east.data.uv_layers.active.data)==list(v.uv[:] for v in west.data.uv_layers.active.data),
    'shared_native_photo_material':list(east.data.materials)==list(west.data.materials),
    'all_ray_visibility_enabled':not east.hide_render and all(getattr(east,k) for k in flags),
    'no_camera_only_shader':all(n.type!='LIGHT_PATH' for mat in east.data.materials for n in mat.node_tree.nodes),
    'no_emission_shader':all(n.type!='EMISSION' for mat in east.data.materials for n in mat.node_tree.nodes)}
images={n.image for mat in east.data.materials for n in mat.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}
checks['photo_dependency_packed']=bool(images) and all(im.packed_file and min(im.size)>0 for im in images)
errors=[k for k,v in checks.items() if not v]
out.write_text(json.dumps({'source':m['candidate'],'source_sha256':sha(m['candidate']),'checks':checks,
    'images':[{'name':im.name,'packed_sha256':hashlib.sha256(bytes(im.packed_file.data)).hexdigest()} for im in images],
    'errors':errors,'pass':not errors,'photorealism_accepted':False,
    'scope':'One east finite-photo surface placement/UV/material/ray-visibility/dependency checks. Not every-window coverage, panorama/parallax, exterior realism, unchanged room illumination or reference acceptance.'},indent=2))
assert not errors,errors
print('EAST_PHOTO_SAVED_AUDIT',flush=True)
