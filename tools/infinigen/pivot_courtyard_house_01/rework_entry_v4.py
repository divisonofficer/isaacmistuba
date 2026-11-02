"""Oak pivot door, glazed sidelight, stone pier, porch lighting and planted edges."""
import bpy,bmesh,math,json,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
oak=pa._flat('entry_v4_oak',(.42,.28,.15),.50,wood=True);dark=bpy.data.materials['layout_v2_dark_frame'];glass=bpy.data.materials['layout_v2_glazing'];stone=bpy.data.materials['pivot_r14_limestone']
def box(c,s):return ('box',c,s,(0,0,0))
def create(n,groups):
 o=pa._prims('PivotEntryV4_'+n,groups);o['ir_room']='entry_deck';return o
# Remove old clinical door AND casing, retain original empty as historical anchor.
for o in list(bpy.data.objects):
 if o.parent and o.parent.name=='door.017':
  for child in list(o.children_recursive):bpy.data.objects.remove(child,do_unlink=True)
  bpy.data.objects.remove(o,do_unlink=True)
changes=[]
for suffix in ['.wall','.exterior']:
 o=bpy.data.objects['hallway_0/0'+suffix]
 bpy.ops.mesh.primitive_cube_add(size=1,location=(24,15.825,1.37));c=bpy.context.object;c.dimensions=(.8,1.75,2.45);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
 mod=o.modifiers.new('entry_glazed_opening','BOOLEAN');mod.operation='DIFFERENCE';mod.solver='EXACT';mod.object=c;bpy.context.view_layer.objects.active=o;bpy.ops.object.modifier_apply(modifier=mod.name);bpy.data.objects.remove(c,do_unlink=True)
 bm=bmesh.new();bm.from_mesh(o.data);caps=[]
 for face in bm.faces:
  co=o.matrix_world@face.calc_center_median();n=o.matrix_world.to_3x3()@face.normal
  if min(abs(co.x-23.6),abs(co.x-24.4))<.003 and abs(n.x)>.98 and 14.94<co.y<16.71 and .14<co.z<2.60:caps.append(face)
 changes.append({'object':o.name,'removed_surface_caps':len(caps)});bmesh.ops.delete(bm,geom=caps,context='FACES');bm.to_mesh(o.data);bm.free()
# Door and side glazing share a coherent thin dark perimeter.
create('dark_frame',[(dark,[box((24,y,1.37),(.085,.055,2.45)) for y in [14.95,16.075,16.70]]+[box((24,15.825,z),(.085,1.805,.045)) for z in [.1675,2.5725]])])
create('glazed_sidelight',[(glass,[box((24,16.3875,1.37),(.012,.57,2.36))])])
hinge=bpy.data.objects.new('PivotEntryV4_physical_hinge',None);bpy.context.scene.collection.objects.link(hinge);hinge.location=(23.98,14.99,.19);hinge.rotation_euler.z=math.radians(65)
leaf=create('open_oak_pivot_door',[(oak,[box((0,.525,1.17),(.055,1.05,2.34))]),(dark,[box((x,.91,1.08),(.028,.035,.36)) for x in [-.045,.045]])]);leaf.parent=hinge
leaf['pivot_state']='open_65_degrees_inward';leaf['clearance_review']='pending render and circulation regression'
# Stone pier beside doorway, connected to ground and under existing canopy.
create('stone_pier',[(stone,[box((24.04,14.68,1.55),(.34,.38,2.81))])])
# Warm recessed ceiling disks: actual area lights under existing porch roof.
for i,(x,y) in enumerate([(24.65,15.4),(25.65,15.4),(25.65,16.35)]):
 create('downlight_trim_'+str(i),[(dark,[('cyl',(x,y,2.925),(.055,.055,.025),(0,0,0))])])
 d=bpy.data.lights.new('entry_v4_warm_downlight_'+str(i),'AREA');d.energy=22;d.color=(1,.76,.51);d.shape='DISK';d.size=.085;o=bpy.data.objects.new(d.name,d);bpy.context.scene.collection.objects.link(o);o.location=(x,y,2.9)
# Large real planter vessels with grounded cached foliage; main path y15..16.1 remains clear.
for i,(x,y,height,asset) in enumerate([(24.85,14.25,1.15,'plant_004.blend'),(24.70,16.58,.86,'plant_012.blend')]):
 create('planter_'+str(i),[(stone,[('cyl',(x,y,.385),(.17,.23,.48),(0,0,0))])])
 with bpy.data.libraries.load(str(R/'data/plant_library'/asset),link=False) as (src,dst):dst.objects=[n for n in src.objects if n=='ir_plant']
 plant=next(o for o in dst.objects if o);bpy.context.scene.collection.objects.link(plant);plant.name='PivotEntryV4_planter_foliage_'+str(i);plant.parent=None;plant.location=(0,0,0);bpy.context.view_layer.update();pts=[plant.matrix_world@Vector(v) for v in plant.bound_box];h=max(v.z for v in pts)-min(v.z for v in pts);plant.scale*=height/max(h,.01);plant.location.x=x;plant.location.y=y;bpy.context.view_layer.update();pts=[plant.matrix_world@Vector(v) for v in plant.bound_box];plant.location.z=.625-min(v.z for v in pts);plant['ir_room']='entry_deck'
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='entry_v4_work_in_progress';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_entry_v4.blend'))
(B/'entry_stage_v4.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','scene':str(F/'scene_rework_entry_v4.blend'),'changes':['open oak pivot door with actual hinge','thin dark framed glazed sidelight','actual widened wall opening','stone pier','warm soffit lights','two planted vessels'],'architectural_caps':changes,'remaining':['Same original camera visual review','Door swing and entry passage clearance','Adjacent study and main hall regression','Additional low planting if reference still sparse']},indent=2)+'\n');print('PIVOT_ENTRY_V4_SAVED',flush=True)
