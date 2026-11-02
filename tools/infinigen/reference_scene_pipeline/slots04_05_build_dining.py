import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector,Matrix
T=Path(__file__).parent;sys.path.insert(0,str(T));from curated_gltf_materials import import_curated_gltf,preserve_native_packed_image
R=T.parents[2];D=R/'data/venue_refs/floor_plans_v3/shared_dining_residence_05';W=R/'out/infinigen_v2/kr_shared_dining_residence_05_48712505/full';out=W/'scene_candidate_slots05_r1.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(W/'scene.blend'));rows=[]
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
base='dual_unit_residential_floor_03';entries=json.loads((D/'native_products_manifest.json').read_text())['assets'];bed,roundlarge,roundsmall=entries
chair=load(base,'living108_armchair_products/asset_manifest.json',0);table=load('commercial_office_floor_02','real_table_candidates/asset_manifest.json',0);night=load(base,'bedroom110_products/asset_manifest.json',0)
place(bed,(1.5,9.1),math.pi/2,'single_bed_north');place(bed,(1.5,7.5),math.pi/2,'single_bed_south')
place(night,(.5,8.3),0,'bedside');place(table,(9.9,8.4),0,'rectangular_shared_table');place(roundsmall,(9.9,5.2),0,'central_round_table');place(roundlarge,(11.4,2.1),0,'large_round_table')
for cx,cy,n,r in [(9.9,8.4,6,1.25),(9.9,5.2,4,1.0),(11.4,2.1,6,1.3)]:
 for i in range(n):
  t=i*2*math.pi/n;place(chair,(cx+r*math.cos(t),cy+r*math.sin(t)),t+math.pi/2,'dining_native_seating_provisional')
# Adult sanitary basin product; room placement remains to be audited.
basin=load(base,'sanitary106_complete_products/asset_manifest.json',0);place(basin,(2.25,2.05),0,'compact_wc_native_basin')
for i,(loc,target,power) in enumerate([((10,7,5),(10,6,0),1800),((3,4,5),(3,4,0),900),((3,9,4),(3,9,0),700)]):
 l=bpy.data.lights.new('Dining_broad_daylight_'+str(i),'AREA');l.energy=power;l.size=5;o=bpy.data.objects.new(l.name,l);bpy.context.scene.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()
packed=[preserve_native_packed_image(im) for im in {n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}]
bpy.ops.wm.save_as_mainfile(filepath=str(out));(D/'candidate_r1_native_inventory.json').write_text(json.dumps({'candidate':str(out),'assets':rows,'packed_images':packed,'limitations':['Single bed frames are real size; mattress and bedding absent, not complete twin bed assemblies','Chairs provisional CH71 lounge chairs; dining seat height mismatch requires replacement','Kitchen cabinetry, laundry equipment, WC pan, food, wall sofa absent','Round tables source materials not optically classified; render pending'],'photorealism_accepted':False},indent=2));(D/'candidate_r1_views.json').write_text(json.dumps([{'name':'overview_r1','location':[7,5.4,24],'target':[7,5.4,0],'overview':True,'ortho_scale':16,'render_width':960,'samples':32},{'name':'shared_dining_context_r1','location':[7.3,6.2,1.65],'target':[10.9,7.8,1.1],'hfov':82,'render_width':960,'samples':32}],indent=2));print('DINING_NATIVE_CANDIDATE_SAVED',out,flush=True)
