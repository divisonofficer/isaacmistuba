"""Read existing shared Infinigen library; native-scale specimen screen without regeneration."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).parent));from curated_gltf_materials import preserve_native_packed_image
r=Path(__file__).resolve().parents[3];lib=r/'data/plant_library_v2';d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/botanical114_products';d.mkdir(exist_ok=True);dst=d/'review_studio.blend';assert not dst.exists();bpy.ops.wm.read_factory_settings(use_empty=True);rows=[];views=[]
for i,name in enumerate(['spiderplant_002','succulent_002','succulent_004']):
 src=lib/(name+'.blend');metadata=json.loads((lib/(name+'.json')).read_text())
 with bpy.data.libraries.load(str(src),link=False) as (s,z):z.objects=list(s.objects)
 loaded=[o for o in z.objects if o];meshes=[o for o in loaded if o.type=='MESH'];assert meshes
 for o in meshes:bpy.context.scene.collection.objects.link(o)
 bpy.context.view_layer.update();matrices={o:o.matrix_world.copy() for o in meshes}
 for o in meshes:o.parent=None;o.matrix_world=matrices[o]
 for o in loaded:
  if o not in meshes:bpy.data.objects.remove(o,do_unlink=True)
 bpy.context.view_layer.update();ps=[o.matrix_world@v.co for o in meshes for v in o.data.vertices];lo=Vector([min(v[k] for v in ps) for k in range(3)]);hi=Vector([max(v[k] for v in ps) for k in range(3)]);size=hi-lo;assert max(size)<2 and size.z>.03,(name,list(size));cx=i*3;delta=Vector((cx-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z))
 for o in meshes:o.location+=delta;o['shared_botanical_asset']=name
 target=Vector((cx,0,size.z*.5))
 for side,off in [('front',(1,-2,1)),('rear',(-1,2,1))]:views.append({'name':name+'_'+side,'location':list(Vector((cx,0,0))+Vector(off)),'target':list(target),'overview':True,'ortho_scale':max(size)*1.4,'render_width':1280,'samples':48})
 for j,(off,power) in enumerate([((0,-2,3),130),((2,1,2),70)]):
  ld=bpy.data.lights.new(name+str(j),'AREA');ld.energy=power;ld.size=1.4;o=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(o);o.location=Vector((cx,0,0))+Vector(off);o.rotation_euler=(target-o.location).to_track_quat('-Z','Y').to_euler()
 rows.append({'id':name,'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'metadata':metadata,'objects':[o.name for o in meshes],'extents_m':list(size),'original_geometry_preserved':True,'translation':list(delta)})
images={n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image};packed=[preserve_native_packed_image(im) for im in images];w=bpy.data.worlds.new('Neutral_botanical_studio');w.use_nodes=True;w.node_tree.nodes.get('Background').inputs['Strength'].default_value=.12;bpy.context.scene.world=w;bpy.ops.wm.save_as_mainfile(filepath=str(dst));(d/'scope.json').write_text(json.dumps({'assets':rows,'packed_images':packed,'scope':'Native-sized bare Infinigen plants from existing shared library. No pots, scene integration or visual acceptance.'},indent=2));(d/'views.json').write_text(json.dumps(views,indent=2));print('SHARED_NATIVE_BOTANICAL_STUDIO_SAVED')
