"""Native shrub variants to fill lower window canopy, before room placement."""
import bpy,json,hashlib,sys,math
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from curated_gltf_materials import import_curated_gltf
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/outdoor_shrub_candidates';D.mkdir(exist_ok=True);O=D/'review_studio.blend';assert not O.exists();h=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
index=json.loads((R/'vendor_datasets/polyhaven_models/polyhaven_object_index.json').read_text());entry=next(x.copy() for x in index['objects'] if x['id']=='PH_shrub_02');p=Path(entry['path']);entry['source_sha256']=h(p);g=json.loads(p.read_text());entry['dependencies']=[{'uri':r['uri'],'sha256':h(p.parent/r['uri'])} for r in g.get('images',[])+g.get('buffers',[]) if r.get('uri') and not r['uri'].startswith('data:')]
bpy.ops.wm.read_factory_settings(use_empty=True);new,objects,profile=import_curated_gltf(entry);rows=[]
for o in objects:
 matrix=o.matrix_world.copy();o.parent=None;o.matrix_world=matrix;bpy.context.view_layer.update();pts=[o.matrix_world@Vector(v) for v in o.bound_box];lo=Vector([min(p[k] for p in pts) for k in range(3)]);hi=Vector([max(p[k] for p in pts) for k in range(3)]);rows.append({'object':o.name,'bounds_lo':list(lo),'bounds_hi':list(hi),'native_faces':len(o.data.polygons)})
w=bpy.data.worlds.new('Shrub_diagnostic_sky');w.use_nodes=True;n=w.node_tree.nodes;l=w.node_tree.links;s=n.new('ShaderNodeTexSky');s.sky_type='NISHITA';s.sun_elevation=math.radians(38);s.sun_rotation=math.radians(135);l.new(s.outputs['Color'],n['Background'].inputs['Color']);n['Background'].inputs['Strength'].default_value=.3;bpy.context.scene.world=w
for im in bpy.data.images:
 if im.source=='FILE':im.pack()
lo=Vector([min(r['bounds_lo'][k] for r in rows) for k in range(3)]);hi=Vector([max(r['bounds_hi'][k] for r in rows) for k in range(3)]);center=(hi+lo)/2
views=[{'name':'four_native_variants','location':list(center+Vector((1,-9,1.5))),'target':list(center),'overview':True,'ortho_scale':7.6,'render_width':960,'samples':24}]
r=rows[1];c=Vector([(a+b)/2 for a,b in zip(r['bounds_lo'],r['bounds_hi'])]);views.append({'name':'variant_b_native_detail','location':list(c+Vector((.7,-3,.6))),'target':list(c),'overview':True,'ortho_scale':2.7,'render_width':960,'samples':24})
bpy.ops.wm.save_as_mainfile(filepath=str(O));(D/'views.json').write_text(json.dumps(views,indent=2));(D/'asset_manifest.json').write_text(json.dumps({'assets':[entry]},indent=2));(D/'scope.json').write_text(json.dumps({'source':str(O),'source_sha256':h(O),'objects':rows,'material_import_contract':profile,'scope':'Four actual native-scale shrub variants and original PBR under diagnostic sky. Not scene-integrated, no optical/reference acceptance.'},indent=2))
