"""Bathroom macro-finish trial on actual native tiles, from retained residential95."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from cut_surface import remove_box_faces
from surface_realism import grout_material
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';B=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
S=B/'scene_candidate_r95.blend';O=B/'scene_candidate_r97.blend';assert not O.exists()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
before=sha(S);bpy.ops.wm.open_mainfile(filepath=str(S))
materials={}
# Reuse audited independent multi-scale roughness/micro-normal from held94, not its colour.
lib=B/'scene_candidate_r94.blend';libsha=sha(lib)
with bpy.data.libraries.load(str(lib),link=False) as (src,dst):dst.materials=['R94_native_stone_visible_wall','R94_native_stone_visible_floor']
for kind,mat in zip(['wall','floor'],dst.materials):
 mat.name='R97_authored_stone_'+kind;n,l=mat.node_tree.nodes,mat.node_tree.links
 uv=n['R93_metric_surface_coordinates'].outputs['UV']
 def vec(name,op,a,b=None):
  x=n.new('ShaderNodeVectorMath');x.name=name;x.operation=op;l.new(a,x.inputs[0])
  if b is not None:
   if isinstance(b,tuple):x.inputs[1].default_value=b
   else:l.new(b,x.inputs[1])
  return x.outputs['Vector']
 scaled=vec('R97_cell_metres','SCALE',uv);n['R97_cell_metres'].inputs['Scale'].default_value=1/.6
 cell=vec('R97_cell_id','FLOOR',scaled);local=vec('R97_local','FRACTION',scaled)
 local=vec('R97_two_metre_albedo','MULTIPLY',local,(.3,.3,0))
 rnd=n.new('ShaderNodeTexWhiteNoise');rnd.name='R97_crop_random';l.new(cell,rnd.inputs['Vector'])
 offset=vec('R97_crop_offset','MULTIPLY',rnd.outputs['Color'],(.7,.7,0));coord=vec('R97_no_wrap','ADD',local,offset)
 im=bpy.data.images.load(str(R/'assets/opticalnav_curated/authored_stone_20261026/warm_greige_stone_basecolor_v1.png'),check_existing=True);im.colorspace_settings.name='sRGB';im.pack()
 tex=n.new('ShaderNodeTexImage');tex.name='R97_synthetic_albedo';tex.image=im;tex.extension='EXTEND';l.new(coord,tex.inputs['Vector']);l.new(tex.outputs['Color'],n['R93_tile_colour_variation'].inputs[1]);materials[kind]=mat
records=[]
for obj in list(bpy.context.scene.objects):
 if not obj.name.startswith('Realism_bathroom_0/2_') or '_tile_' not in obj.name:continue
 kind='floor' if '_floor_tile_' in obj.name else 'wall';obj.data=obj.data.copy();mesh=obj.data
 geom=hashlib.sha256(repr(([(tuple(v.co)) for v in mesh.vertices],[tuple(f.vertices) for f in mesh.polygons])).encode()).hexdigest()
 old=[m.name if m else None for m in mesh.materials];index=mesh.uv_layers.active_index
 layer=mesh.uv_layers.get('R93_StoneMetres') or mesh.uv_layers.new(name='R93_StoneMetres')
 for face in mesh.polygons:
  normal=(obj.matrix_world.to_3x3().inverted().transposed()@face.normal).normalized()
  for li in face.loop_indices:
   p=obj.matrix_world@mesh.vertices[mesh.loops[li].vertex_index].co
   layer.data[li].uv=(p.x,p.y) if abs(normal.z)>.5 else ((p.y,p.z) if abs(normal.x)>.5 else (p.x,p.z))
 mesh.uv_layers.active_index=index;mesh.materials.clear();mesh.materials.append(materials[kind])
 for face in mesh.polygons:face.material_index=0
 records.append({'object':obj.name,'kind':kind,'geometry_sha256':geom,'old_materials':old,'new_material':materials[kind].name})
assert len(records)==131
for name in ['bathroom_0/2.wall','bathroom_0/2.floor']:
 obj=bpy.data.objects[name];obj.data=obj.data.copy();obj.data.materials.clear();obj.data.materials.append(grout_material('R97_warm_grout_'+name,(.30,.27,.23)))
 for f in obj.data.polygons:f.material_index=0
skirt=bpy.data.objects['skirtingboard_support'];skirt.data=skirt.data.copy()
points=[skirt.matrix_world@v.co for v in skirt.data.vertices if not(-.01<=(skirt.matrix_world@v.co).x<=3.01 and 2.99<=(skirt.matrix_world@v.co).y<=6.01)]
removed=remove_box_faces(skirt,(1.5,4.5,.18),(3,3,.30));assert removed>0
bv=BVHTree.FromPolygons([skirt.matrix_world@v.co for v in skirt.data.vertices],[tuple(f.vertices) for f in skirt.data.polygons]);dist=[bv.find_nearest(p)[3] for p in points];assert max(dist)<1e-4
bpy.ops.wm.save_as_mainfile(filepath=str(O));assert sha(S)==before and sha(lib)==libsha
meta={'source':str(S),'source_sha256':before,'candidate':str(O),'candidate_sha256':sha(O),'roughness_graph_source':str(lib),'roughness_source_sha256':libsha,'surfaces':records,'removed_local_trim_split_faces':removed,'outside_trim_samples':len(dist),'outside_trim_max_distance_m':max(dist),'change':'101 main bathroom actual131tiles: synthetic warm mineral BaseColor, independent existing roughness/micro-normal, real grout/bevel preserved; local PVC removal. Real shower92 preserved. No furniture,lights,world or cameras edited.','photorealism_accepted':False,'scope':'Only101 main bathroom. Synthetic1254square albedo, not scanned/measuredBRDF. Existing600mm tile layout retained, not reference large-format slab match. Saved-source checks and RGB screening pending.'}
inherited=json.loads((D/'realism_refinement_r95.json').read_text());inherited.update(meta)
(D/'realism_refinement_r97.json').write_text(json.dumps(inherited,indent=2))
