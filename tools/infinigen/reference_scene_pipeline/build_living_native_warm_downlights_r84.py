"""Native four-fixture warm living rig, same room/world/exposure; trial only."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from cut_surface import remove_box_faces
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';B=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';S=B/'scene_candidate_r83.blend';O=B/'scene_candidate_r84.blend';A=D/'real_recessed_light_candidate';assert not O.exists();assert (A/'blind_material_review.json').exists();asset=A/'functional_unlit.blend';names=json.loads((A/'review_scope.json').read_text())['objects'];bpy.ops.wm.open_mainfile(filepath=str(S));scene=bpy.context.scene;ceiling=bpy.data.objects['living-room_0/0.ceiling'];cz=min((ceiling.matrix_world@Vector(v)).z for v in ceiling.bound_box);ceiling.data=ceiling.data.copy();old=bpy.data.objects['res03_area_101_living'];oldpower=old.data.energy;assert old.type=='LIGHT' and oldpower>0;oldfixture=[o for o in scene.objects if o.get('program_key')=='101_living_ceiling_fixture'];assert len(oldfixture)==1
removed=[old.name,oldfixture[0].name];bpy.data.objects.remove(old,do_unlink=True);bpy.data.objects.remove(oldfixture[0],do_unlink=True);records=[]
for i,(x,y) in enumerate([(1.6,6.75),(5.4,6.75),(1.6,8.75),(5.4,8.75)]):
 # Blender replaces this list's strings with loaded datablocks on exit.
 # Keep the reusable source-name list immutable across the four imports.
 with bpy.data.libraries.load(str(asset),link=False) as (src,dst):dst.objects=list(names)
 parts=[o for o in dst.objects if o and o.type=='MESH'];assert len(parts)==2
 for o in parts:scene.collection.objects.link(o)
 bpy.ops.object.select_all(action='DESELECT')
 for o in parts:o.select_set(True)
 bpy.context.view_layer.objects.active=parts[0];bpy.ops.object.join();o=bpy.context.object;o.name=f'Res03_r84_101_living_native_downlight_{i}';bpy.context.view_layer.update();pts=[o.matrix_world@Vector(v) for v in o.bound_box];lo=Vector([min(p[k] for p in pts) for k in range(3)]);hi=Vector([max(p[k] for p in pts) for k in range(3)]);o.location+=Vector((x-(lo.x+hi.x)/2,y-(lo.y+hi.y)/2,cz+.004-hi.z));o['reference_scene_owner']='dual_unit_residential_floor_03';o['program_key']='101_living_ceiling_fixture' if i==0 else f'101_living_native_downlight_{i}';o['audit_kind']='ceiling_fixture';o['reference_ceiling_detail']=True;o['original_asset_id']='HSSD_8830afcbb0fd7442c0dd7a27c05129c65e0be283';assert len(o.data.polygons)==6294
 for j,m in enumerate(o.data.materials):
  if m and '::000' in m.name:
   m=m.copy();o.data.materials[j]=m;bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');bb=m.node_tree.nodes.new('ShaderNodeBlackbody');bb.inputs['Temperature'].default_value=3200;m.node_tree.links.new(bb.outputs['Color'],bs.inputs['Emission Color']);bs.inputs['Emission Strength'].default_value=2
 cut=remove_box_faces(ceiling,(x,y,cz),(.07,.07,.06));assert cut>0
 light=bpy.data.lights.new(f'Realism_101_living_downlight_{i}','AREA');light.shape='DISK';light.size=.06;light.use_nodes=True;light.energy=oldpower/4;em=next(n for n in light.node_tree.nodes if n.type=='EMISSION');em.inputs['Strength'].default_value=oldpower/4;bb=light.node_tree.nodes.new('ShaderNodeBlackbody');bb.inputs['Temperature'].default_value=3200;light.node_tree.links.new(bb.outputs['Color'],em.inputs['Color']);lamp=bpy.data.objects.new(light.name,light);scene.collection.objects.link(lamp);lamp.location=(x,y,cz-.009)
 records.append({'object':o.name,'asset_faces':len(o.data.polygons),'xy':[x,y],'ceiling_z':cz,'native_top_z':cz+.004,'native_bottom_z':cz-.007,'concealed_square_cutout_m':.07,'removed_ceiling_split_faces':cut,'area_light':lamp.name,'area_power':light.energy,'node_strength':em.inputs['Strength'].default_value,'temperature_K':3200,'visible_diffuser_emission_strength':2,'model_scale_unchanged':True})
coves=[]
for o in scene.objects:
 if o.type!='MESH' or not str(o.get('program_key','')).startswith('101_living_cove_led'):continue
 for j,m in enumerate(o.data.materials):
  if not m or not m.use_nodes:continue
  m=m.copy();o.data.materials[j]=m;bs=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
  if bs:
   bb=m.node_tree.nodes.new('ShaderNodeBlackbody');bb.inputs['Temperature'].default_value=3200;m.node_tree.links.new(bb.outputs['Color'],bs.inputs['Emission Color']);coves.append({'object':o.name,'temperature_K':3200,'emission_strength':bs.inputs['Emission Strength'].default_value})
assert len(records)==4;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(O));(D/'realism_refinement_r84.json').write_text(json.dumps({'source':str(S),'source_sha256':hashlib.sha256(S.read_bytes()).hexdigest(),'candidate':str(O),'candidate_sha256':hashlib.sha256(O.read_bytes()).hexdigest(),'change':'Only101living practical rig: replace central square fixture+area with4 actual native round fixtures+4 small disk emitters,3200K. Native dimensions preserved,hidden square ceiling apertures covered by round trims. Existing living cove emission temperature set3200K,other rooms/world/exposure unchanged.','source_asset':str(asset),'source_asset_sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),'removed':removed,'replaced_area_power':oldpower,'summed_new_area_power':sum(r['area_power'] for r in records),'fixtures':records,'coves':coves,'scope':'Approximate rendering rig:area transport lights plus low-strength visible diffusers,not calibrated lumens/photometry. Saved mounting/light elevation,actual lit-room/reference RGB and regression needed. Room fixtures andlight distribution change together; not a shader-only isolation claim.','retained_revision':83,'photorealism_accepted':False},indent=2)+'\n');print('LIVING_WARM_DOWNLIGHTS_R84_SAVED',flush=True)
