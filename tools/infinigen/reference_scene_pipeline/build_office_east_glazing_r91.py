"""Reference-directed native east glazing; fixed topology/lighting, not adopted."""
import bpy,json,sys,math,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'modules/infinigen'));sys.path.insert(0,str(Path(__file__).parent))
from infinigen.assets.objects.windows.window import WindowFactory
from cut_surface import remove_box_faces
D=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';B=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';S=B/'scene_candidate_r88.blend';OUT=B/'scene_candidate_r91.blend';assert not OUT.exists();assert (D/'native_fullheight_glazing_pilot02/blind_visual_review.json').exists();before=hashlib.sha256(S.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(S))
normal=Vector((1,.08,0)).normalized();tangent=Vector((-.08,1,0)).normalized();zaxis=Vector((0,0,1));basis=Matrix(((tangent.x,normal.x,0,0),(tangent.y,normal.y,0,0),(0,0,1,0),(0,0,0,1)));inv=basis.inverted();shell=[bpy.data.objects[n] for n in ['office_0/9.wall','office_0/9.exterior']];records=[]
def material(name,rgb,rough,trans=0):
 m=bpy.data.materials.new(name);m.use_nodes=True;p=m.node_tree.nodes['Principled BSDF'];p.inputs['Base Color'].default_value=(*rgb,1);p.inputs['Roughness'].default_value=rough;p.inputs['Transmission Weight'].default_value=trans;p.inputs['IOR'].default_value=1.5;return m
black=material('R91_powder_coated_black_frame',(.018,.022,.026),.32);glass=material('R91_physical_clear_glass',(.99,.995,1),.015,1)
for index,(ya,yb) in enumerate([(10.6,13.35),(13.65,17.65)],13):
 native=bpy.data.objects[f'WindowFactory(3498).spawn_asset({index})'];placeholder=native.parent;assert placeholder.name==f'window.{index:03d}'
 y=(ya+yb)/2;plane=(15.8401+15.9490)/2;point=normal*plane+tangent*((y-normal.y*plane)/tangent.y);bottom=.12;top=2.65;width=(yb-ya)/tangent.y;height=top-bottom
 # Native geometry has FrameWidth extra total extent. Regenerate to exact envelope, no nonuniform scaling.
 fac=WindowFactory(87430,curtain=False,shutter=False);sample=fac.sample_asset_params;control={'PanelHAmount':1,'PanelVAmount':3,'SubPanelHAmount':1,'SubPanelVAmount':1,'FrameWidth':.045,'SubFrameWidth':.018,'SubFrameThickness':.06,'GlassThickness':.008}
 def controlled(*args,**kw):p=sample(*args,**kw);p.update(control);return p
 fac.sample_asset_params=controlled;o=fac.create_asset(dimensions=(width-.045,height-.045,.12),open=False);o.name=f'Office02_r91_east_glazing_{index}'
 for i,m in enumerate(o.data.materials):
  if m==fac.params['Material']:o.data.materials[i]=glass
  elif m==fac.params['FrameMaterial']:o.data.materials[i]=black
 bpy.context.view_layer.update();assert abs(o.dimensions.x-width)<1e-4 and abs(o.dimensions.z-height)<1e-4
 o.rotation_euler.z=math.atan2(tangent.y,tangent.x);o.location=point;bpy.context.view_layer.update();pts=[o.matrix_world@Vector(v) for v in o.bound_box];o.location.z+=bottom-min(p.z for p in pts);bpy.context.view_layer.update()
 # Cut both actual interior and exterior shell meshes in facade tangent/normal coordinates.
 cutcenter=inv@Vector((point.x,point.y,(bottom+top)/2));cutsize=(width+.003,.42,height+.003);cuts=[]
 for wall in shell:
  old=wall.matrix_world.copy();wall.data=wall.data.copy();wall.matrix_world=inv@old
  try:count=remove_box_faces(wall,cutcenter,cutsize)
  finally:wall.matrix_world=old
  cuts.append({'wall':wall.name,'removed_split_faces':count})
 assert all(x['removed_split_faces']>0 for x in cuts)
 oldnames=[c.name for c in native.children_recursive]+[native.name]
 for child in list(native.children_recursive):bpy.data.objects.remove(child,do_unlink=True)
 bpy.data.objects.remove(native,do_unlink=True)
 # Placeholder is an invisible procedural locator, no longer used by new assembly.
 placeholder.hide_render=True
 o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=f'east_native_fullheight_glazing_{index}';o['construction_source']='WindowFactory controlled native geometry'
 records.append({'object':o.name,'native_seed':87430,'parameters':control,'target_y_interval':[ya,yb],'target_bounds_z':[bottom,top],'width_m':width,'native_faces':len(o.data.polygons),'removed_objects':oldnames,'shell_cuts':cuts,'world_location':list(o.location),'world_rotation':list(o.rotation_euler)})
assert hashlib.sha256(S.read_bytes()).hexdigest()==before
bpy.ops.wm.save_as_mainfile(filepath=str(OUT));(D/'realism_refinement_r91.json').write_text(json.dumps({'source':str(S),'source_sha256':before,'candidate':str(OUT),'candidate_sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),'change':'Two east open-workplace native windows replaced by broad fullheight3-pane manufactured assemblies; both interior/exterior shell apertures cut. Room topology and all other objects/materials/world/exposure preserved. No source90 HDR adopted.','records':records,'retained_revision':88,'photorealism_accepted':False,'scope':'Build only. Need saved-file ray opening/frame/wall fit, materials/required-space/circulation checks and fixed-camera A/B before retention.'},indent=2)+'\n');print('EAST_GLAZING_R91_SAVED',flush=True)
