"""Inspect actual modular facade assembly at native dimensions before scene integration."""
import bpy,json,hashlib,sys,math
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from curated_gltf_materials import import_curated_gltf
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/outdoor_facade_candidates';D.mkdir(exist_ok=True);out=D/'review_studio.blend';assert not out.exists()
index=json.loads((R/'vendor_datasets/polyhaven_models/polyhaven_object_index.json').read_text());entry=next(x.copy() for x in index['objects'] if x['id']=='PH_modular_urban_apartments_facade')
path=Path(entry['path']);sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();entry['source_sha256']=sha(path);data=json.loads(path.read_text());entry['dependencies']=[]
for row in data.get('buffers',[])+data.get('images',[]):
 uri=row.get('uri')
 if uri and not uri.startswith('data:'):entry['dependencies'].append({'uri':uri,'sha256':sha(path.parent/uri)})
bpy.ops.wm.read_factory_settings(use_empty=True);new,objects,profile=import_curated_gltf(entry)
rows=[]
for o in objects:
 pts=[o.matrix_world@Vector(v) for v in o.bound_box];lo=[min(p[k] for p in pts) for k in range(3)];hi=[max(p[k] for p in pts) for k in range(3)]
 rows.append({'object':o.name,'lo':lo,'hi':hi,'faces':len(o.data.polygons),'world_matrix':[list(x) for x in o.matrix_world]})
for im in bpy.data.images:
 if im.source=='FILE':im.pack()
w=bpy.data.worlds.new('Facade_diagnostic_sky');w.use_nodes=True;n=w.node_tree.nodes;l=w.node_tree.links;sky=n.new('ShaderNodeTexSky');sky.sky_type='NISHITA';sky.sun_elevation=math.radians(38);sky.sun_rotation=math.radians(135);l.new(sky.outputs['Color'],n['Background'].inputs['Color']);n['Background'].inputs['Strength'].default_value=.3;bpy.context.scene.world=w
views=[{'name':'full_pack_front','location':[1,-45,10],'target':[1,0,7],'overview':True,'ortho_scale':58,'render_width':960,'samples':24},{'name':'three_bay_front','location':[15,-24,10],'target':[15,0,7],'overview':True,'ortho_scale':23,'render_width':960,'samples':24},{'name':'three_bay_reverse','location':[15,24,10],'target':[15,0,7],'overview':True,'ortho_scale':23,'render_width':960,'samples':24}]
bpy.ops.wm.save_as_mainfile(filepath=str(out));(D/'views.json').write_text(json.dumps(views,indent=2));(D/'inventory.json').write_text(json.dumps(rows,indent=2));(D/'asset_manifest.json').write_text(json.dumps({'assets':[entry]},indent=2));(D/'scope.json').write_text(json.dumps({'source':str(out),'source_sha256':sha(out),'asset':entry['id'],'native_objects':len(objects),'native_faces':sum(len(o.data.polygons) for o in objects),'material_import_contract':profile,'scope':'Unedited native demonstration module arrangement, not yet a scene or approved exterior. No box proxy buildings. Visual screening must identify correct facing and candidate group.'},indent=2))
