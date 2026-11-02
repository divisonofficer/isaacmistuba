"""Actual curved cloth product models at native dimensions, no room edits."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from curated_gltf_materials import import_curated_gltf
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/real_pillow_candidates';D.mkdir(exist_ok=True);out=D/'review_studio.blend';assert not out.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
index=json.loads((R/'vendor_datasets/polyhaven_models/polyhaven_object_index.json').read_text());e=next(x.copy() for x in index['objects'] if x['id']=='PH_throw_pillows_01');p=Path(e['path']);e['source_sha256']=sha(p);g=json.loads(p.read_text());e['dependencies']=[{'uri':v['uri'],'sha256':sha(p.parent/v['uri'])} for v in g.get('images',[])+g.get('buffers',[]) if v.get('uri') and not v['uri'].startswith('data:')]
bpy.ops.wm.read_factory_settings(use_empty=True);new,objects,profile=import_curated_gltf(e);rows=[];views=[]
for o in objects:
 matrix=o.matrix_world.copy();o.parent=None;o.matrix_world=matrix;bpy.context.view_layer.update();pts=[o.matrix_world@v.co for v in o.data.vertices];lo=Vector([min(p[k] for p in pts) for k in range(3)]);hi=Vector([max(p[k] for p in pts) for k in range(3)]);center=(lo+hi)/2
 rows.append({'object':o.name,'bounds_lo':list(lo),'bounds_hi':list(hi),'extents_m':list(hi-lo),'faces':len(o.data.polygons),'matrix':[list(v) for v in o.matrix_world]})
for i,(offset,power,size) in enumerate([((-.5,-1,1.2),45,.8),((.8,.5,.5),20,.6)]):
 ld=bpy.data.lights.new('Pillow_studio_area'+str(i),'AREA');ld.energy=power;ld.size=size;ob=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(ob);ob.location=offset;ob.rotation_euler=(Vector((0,0,.25))-ob.location).to_track_quat('-Z','Y').to_euler()
w=bpy.data.worlds.new('Pillow_neutral_world');w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=.10;bpy.context.scene.world=w
views=[{'name':'native_pillow_pair_front','location':[.1,-1.8,1.0],'target':[0,0,.23],'overview':True,'ortho_scale':1.25,'render_width':960,'samples':32},{'name':'native_pillow_pair_reverse','location':[-.1,1.7,.9],'target':[0,0,.23],'overview':True,'ortho_scale':1.25,'render_width':960,'samples':32}]
for im in bpy.data.images:
 if im.source=='FILE':im.pack()
bpy.ops.wm.save_as_mainfile(filepath=str(out));(D/'views.json').write_text(json.dumps(views,indent=2));(D/'scope.json').write_text(json.dumps({'source':str(out),'source_sha256':sha(out),'assets':[e],'objects':rows,'material_import_contract':profile,'scope':'Native source geometry/UV/size and imported PBR under diagnostic area lights. No scene placement/cloth simulation/reference approval.'},indent=2))
