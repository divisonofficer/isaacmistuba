"""Saved procedural stone contracts and bounded wet-room trim checks, not realism."""
import bpy,json,hashlib,sys,argparse
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True);p.add_argument('--out',type=Path)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
meta=json.loads((D/f'realism_refinement_r{a.revision}.json').read_text())
source=Path(meta['candidate']);sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(source)==meta['candidate_sha256'];assert sha(meta['source'])==meta['source_sha256']
out=a.out or D/f'bathroom_stone_saved_audit_r{a.revision}.json';assert not out.exists()
bpy.ops.wm.open_mainfile(filepath=str(source));errors=[];checks=[]
target_objects=list(bpy.context.scene.objects)
v2=meta['stone_finish'].get('contract_version',1)>=2
declared_names={row['object'] for row in meta['stone_finish']['surfaces']}
physical_tile_names={obj.name for obj in target_objects if obj.type=='MESH' and obj.name.startswith('Realism_bathroom_0/2_') and '_tile_' in obj.name}
missing_actual_tiles=sorted(physical_tile_names-declared_names)
if not physical_tile_names:errors.append('No actual target-room tile solids found')
if missing_actual_tiles:errors.append('Stone contract misses actual tile solids: '+str(len(missing_actual_tiles)))
visibility=[]
if v2:
    sys.path.insert(0,str(Path(__file__).parent))
    from surface_visibility import first_surface_hits
    tiles=[bpy.data.objects[row['object']] for row in meta['stone_finish']['surfaces']]
    visibility=first_surface_hits(tiles,[
        {'label':'west_wall','origin':[1,4.7,1.6],'direction':[-1,0,0],'distance':1.3},
        {'label':'north_wall','origin':[1,4.5,1.6],'direction':[0,1,0],'distance':2},
        {'label':'floor','origin':[1,4.7,.6],'direction':[0,0,-1],'distance':.7}])
    for row in visibility:
        if not row['first_hit'] or not str(row['first_hit']['material']).startswith('R94_native_stone_visible_'):
            errors.append('Actual tile sample has wrong material:'+row['label'])
def upstream(socket):
    seen=set();todo=[link.from_node for link in socket.links]
    while todo:
        node=todo.pop()
        if node in seen:continue
        seen.add(node)
        todo.extend(link.from_node for inp in node.inputs for link in inp.links)
    return seen
def geometry(obj):
    return ([tuple(v.co) for v in obj.data.vertices],[tuple(f.vertices) for f in obj.data.polygons],
            [list(row) for row in obj.matrix_world])
names=[row['object'] for row in meta['stone_finish']['surfaces']]
actual={name:bpy.data.objects[name] for name in names}
with bpy.data.libraries.load(meta['source'],link=False) as (src,dst):
    dst.objects=names+['skirtingboard_support']
originals=dst.objects
for obj in originals:bpy.context.scene.collection.objects.link(obj)
bpy.context.view_layer.update()
for i,name in enumerate(names):
    obj=actual[name];material=obj.data.materials[0]
    bs=next(n for n in material.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    output=next(n for n in material.node_tree.nodes if n.type=='OUTPUT_MATERIAL' and n.is_active_output)
    colour=upstream(bs.inputs['Base Color']);rough=upstream(bs.inputs['Roughness']);normal=upstream(bs.inputs['Normal'])
    result={'object':name,'geometry_unchanged':geometry(obj)==geometry(originals[i]),
        'native_vein_graph_active':any(n.type=='TEX_VORONOI' for n in colour),
        'metric_uv_used':any(n.type=='UVMAP' and n.uv_map=='R93_StoneMetres' for n in colour),
        'metric_uv_exists':obj.data.uv_layers.get('R93_StoneMetres') is not None,
        'roughness_three_sources_active':all(material.node_tree.nodes[n] in rough for n in ['R93_macro_1p25m','R93_meso_2p5cm','R93_tile_variation']),
        'normal_chain_matches_contract':(material.node_tree.nodes['R93_micro_relief_80um'] in normal and
            material.node_tree.nodes['R93_grout_normal_recess_1p2mm'] not in normal) if v2 else all(material.node_tree.nodes[n] in normal for n in ['R93_micro_relief_80um','R93_grout_normal_recess_1p2mm']),
        'nonmetallic_dielectric':not bs.inputs['Metallic'].is_linked and bs.inputs['Metallic'].default_value==0 and abs(bs.inputs['IOR'].default_value-1.5)<1e-5,
        'no_displaced_mesh_claim':not output.inputs['Displacement'].is_linked}
    for key,value in result.items():
        if key!='object' and not value:errors.append(name+':'+key)
    checks.append(result)
if v2:
    for name in meta['stone_finish']['backing_objects']:
        mat=bpy.data.objects[name].data.materials[0]
        if mat.name!='R94_local_warm_grout':errors.append('Backing is not local grout:'+name)
skirt=bpy.data.objects['skirtingboard_support'];old=originals[-1]
tree=BVHTree.FromPolygons([skirt.matrix_world@v.co for v in skirt.data.vertices],[tuple(f.vertices) for f in skirt.data.polygons])
outside=[old.matrix_world@v.co for v in old.data.vertices if not
         (-.01<=(old.matrix_world@v.co).x<=3.01 and 2.99<=(old.matrix_world@v.co).y<=6.01)]
distances=[tree.find_nearest(point)[3] for point in outside]
if not distances or max(distances)>1e-4:errors.append('Outside target skirting vertices changed')
rays=[]
for origin,direction in [((.4,4.5,.18),(-1,0,0)),((2.6,4.5,.18),(1,0,0)),((1.5,5.6,.18),(0,1,0)),((1.,3.4,.18),(0,-1,0))]:
    hit=tree.ray_cast(Vector(origin),Vector(direction),.5)[0]
    rays.append({'origin':origin,'direction':direction,'target_trim_clear':hit is None})
    if hit is not None:errors.append('Target trim remains on sample ray')
out.write_text(json.dumps({'source':str(source),'source_sha256':sha(source),'checks':checks,
    'contract_version':2 if v2 else 1,'actual_tile_sample_hits':visibility,
    'physical_tile_count':len(physical_tile_names),'undeclared_actual_tiles':missing_actual_tiles,
    'visibility_scope':'Tile-only sample rays prove tile material targeting; not full renderer visibility or transparent occlusion certification. Original comparison objects excluded from ray probes.',
    'outside_trim_original_vertex_samples':len(distances),'outside_trim_max_distance_m':max(distances),
    'target_trim_rays':rays,'errors':errors,'pass':not errors,'photorealism_accepted':False,
    'scope':'Exact original wall/floor geometry, active material graph and four trim rays, outside original trim vertex surface-distance samples. Not visual realism,measured reflectance,physical grout displacement,complete trim topology/volume or full navigation certification.'},indent=2))
print('BATHROOM_STONE_SAVED_AUDIT',len(errors),flush=True);assert not errors,errors
