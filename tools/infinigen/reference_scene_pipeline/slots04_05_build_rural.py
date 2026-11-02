import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector,Matrix
T=Path(__file__).parent;sys.path.insert(0,str(T));from curated_gltf_materials import import_curated_gltf,preserve_native_packed_image
R=T.parents[2];D=R/'data/venue_refs/floor_plans_v3/rural_stone_cottage_04';W=R/'out/infinigen_v2/kr_rural_stone_cottage_04_48712504/full';out=W/'scene_candidate_slots04_r1.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(W/'scene.blend'));rows=[]
def load(ref,file,i=0):return json.loads((R/'data/venue_refs/floor_plans_v3'/ref/file).read_text())['assets'][i]
def place(e,xy,angle=0,role=''):
 new,objs,profile=import_curated_gltf(e,repair_nonpositive_ior=1.5);bpy.context.view_layer.update();m={o:o.matrix_world.copy() for o in objs}
 for o in objs:o.parent=None;o.matrix_world=m[o]
 rot=Matrix.Rotation(angle,4,'Z')
 for o in objs:o.matrix_world=rot@o.matrix_world
 bpy.context.view_layer.update();pts=[o.matrix_world@v.co for o in objs for v in o.data.vertices];lo=Vector([min(v[k] for v in pts) for k in range(3)]);hi=Vector([max(v[k] for v in pts) for k in range(3)]);dim=hi-lo;assert all(.05<x<5 for x in dim),list(dim)
 delta=Vector((xy[0]-(hi.x+lo.x)/2,xy[1]-(hi.y+lo.y)/2,.025-lo.z))
 for o in objs:o.location+=delta;o['reference_role']=role;o['source_asset_id']=e['id']
 rows.append({'id':e['id'],'name':e.get('name'),'role':role,'dimensions_m':list(dim),'position_xy':xy,'rotation_rad':angle,'scale_policy':'native unchanged','triangles':sum(len(o.data.polygons) for o in objs),'material_profile':profile})
 return dim
base='dual_unit_residential_floor_03';bed=load(base,'real_bed_candidates/asset_candidates_manifest.json',2);table=load('commercial_office_floor_02','real_table_candidates/asset_manifest.json',1);chair=load(base,'living108_armchair_products/asset_manifest.json',0);night=load(base,'bedroom110_products/asset_manifest.json',0)
place(bed,(1.65,9.25),0,'master_bed');place(night,(.55,10.7),0,'bedside');place(table,(6.75,5),0,'living_dining_table');place(table,(4.7,13.9),0,'study_worktable')
for xy,ang in [((5.8,3.9),0),((7.7,3.9),0),((5.8,6.1),math.pi),((7.7,6.1),math.pi),((4.7,12.7),0),((8.6,9.5),math.pi/2)]:place(chair,xy,ang,'native_wood_upholstered_seating')
# Architectural timber members only: no product furniture primitives.
def material(n,col,rough):
 m=bpy.data.materials.new(n);m.use_nodes=True;b=m.node_tree.nodes.get('Principled BSDF');b.inputs['Base Color'].default_value=(*col,1);b.inputs['Roughness'].default_value=rough;b.inputs['IOR'].default_value=1.5;noise=m.node_tree.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=7;noise.inputs['Detail'].default_value=4;bump=m.node_tree.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.28;bump.inputs['Distance'].default_value=.04;m.node_tree.links.new(noise.outputs['Fac'],bump.inputs['Height']);m.node_tree.links.new(bump.outputs['Normal'],b.inputs['Normal']);return m
timber=material('Cottage_oak_beams_inferred_optics',(.12,.065,.025),.63);stone=material('Cottage_warm_limestone_inferred_optics',(.31,.28,.22),.83)
for o in list(bpy.context.scene.objects):
 if o.type=='MESH' and 'wall' in o.name.lower():
  o.data.materials.clear();o.data.materials.append(stone)
def beam(n,loc,size):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=n;o.dimensions=size;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(timber);mod=o.modifiers.new('timber_edge_wear','BEVEL');mod.width=.025;mod.segments=3
for y in [3.1,5.1,7.1,9.1,11.1,13.1,15.1]:beam('Cottage_structural_crossbeam',(6.8,y,2.72),(13.6,.18,.24))
beam('Cottage_porch_deck',(5.2,1.2,-.07),(10.4,2.4,.14))
for x in [.25,3.5,6.8,10.15]:beam('Cottage_porch_post',(x,.25,1.35),(.18,.18,2.7))
# Renderable roof draft deliberately deferred to preserve cutaway inspection.
for i,(loc,target,power) in enumerate([((6.8,6,5),(6.8,7,0),1400),((4.7,13,4.8),(4.7,13,0),650)]):
 l=bpy.data.lights.new('Cottage_broad_daylight_'+str(i),'AREA');l.energy=power;l.size=5;o=bpy.data.objects.new(l.name,l);bpy.context.scene.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()
packed=[preserve_native_packed_image(im) for im in {n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}]
bpy.ops.wm.save_as_mainfile(filepath=str(out));(D/'candidate_r1_native_inventory.json').write_text(json.dumps({'candidate':str(out),'assets':rows,'packed_images':packed,'limitations':['Native catalog furniture selected as provisional rural substitutes, style not accepted','Stone shader procedural draft; actual masonry courses, slate roof, garden and kitchens missing','Native queen bed size kept unchanged; support and circulation pending audit'],'photorealism_accepted':False},indent=2));(D/'candidate_r1_views.json').write_text(json.dumps([{'name':'overview_r1','location':[6.8,8.8,28],'target':[6.8,8.8,0],'overview':True,'ortho_scale':19,'render_width':960,'samples':32},{'name':'living_context_r1','location':[4.1,3,1.65],'target':[7.2,8.3,1.1],'hfov':78,'render_width':960,'samples':32}],indent=2));print('RURAL_NATIVE_CANDIDATE_SAVED',out,flush=True)
