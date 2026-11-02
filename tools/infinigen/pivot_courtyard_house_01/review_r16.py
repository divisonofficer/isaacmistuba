"""Complete utility-room reference programmes and small bedroom/entry furniture."""
import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
pa.SURFACE_DETAIL=False
base=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';run=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full';fixes=[]
def remove(o):
 for q in reversed([o,*o.children_recursive]):bpy.data.objects.remove(q,do_unlink=True)
def mat(name,c,r=.7,metal=0):
 m=bpy.data.materials.new(name);m.use_nodes=True;b=m.node_tree.nodes['Principled BSDF'];b.inputs['Base Color'].default_value=(*c,1);b.inputs['Roughness'].default_value=r;b.inputs['Metallic'].default_value=metal;return m
fz=.14754
oak=pa._flat('pivot_r16_residential_oak',(.48,.34,.22),.6,wood=True);white=mat('pivot_r16_appliance_enamel',(.76,.76,.72),.4);stone=bpy.data.materials['pivot_r14_limestone'];steel=bpy.data.materials['pivot_r14_brushed_hardware'];dark=mat('pivot_r16_dark_glass',(.014,.024,.03),.18);cloth=mat('pivot_r16_linen_shade',(.72,.67,.57),.9)
# The laundry reference has washer AND dryer, plus a utility sink. Replace the
# one-appliance shrunken native run using the same engine primitive builders.
for o in list(bpy.data.objects):
 if o.parent is None and o.get('ir_room')=='utility_0/0' and 'LaundryRunFactory' in o.name:remove(o)
for i,(x,role) in enumerate([(8.65,'washing_machine'),(9.30,'tumble_dryer')]):
 groups=[(white,[('box',(x,11.02,fz+.43),(.60,.62,.84),(0,0,0))]),(steel,[('cyl',(x,10.696,fz+.40),(.225,.225,.035),(math.pi/2,0,0)),('cyl',(x-.20,10.693,fz+.745),(.025,.025,.020),(math.pi/2,0,0))]),(dark,[('cyl',(x,10.674,fz+.40),(.185,.185,.014),(math.pi/2,0,0)),('box',(x+.08,10.696,fz+.75),(.16,.014,.052),(0,0,0))])]
 o=pa._prims(f'PivotLaundryApplianceFactory({2100+i}).spawn_asset({2100+i})',groups);o['ir_room']='utility_0/0';o['ir_role']=role
# Stone worktop cut into four segments around a genuinely recessed sink.
z=fz+.90
parts=[('box',((8.30+9.73)/2,11.02,z),(9.73-8.30,.66,.035),(0,0,0)),('box',((10.15+10.30)/2,11.02,z),(10.30-10.15,.66,.035),(0,0,0)),('box',(9.94,10.765,z),(.42,.15,.035),(0,0,0)),('box',(9.94,11.285,z),(.42,.13,.035),(0,0,0))]
bowl=[('box',(9.94,11.025,fz+.73),(.40,.36,.015),(0,0,0))]+[('box',(x,11.025,fz+.815),(.012,.36,.17),(0,0,0)) for x in (9.735,10.145)]+[('box',(9.94,y,fz+.815),(.42,.012,.17),(0,0,0)) for y in (10.84,11.21)]
upper=[('box',(9.3,11.17,fz+1.82),(2.0,.34,.64),(0,0,0))]
fronts=[('box',(8.30+(k+.5)*2/5,10.99,fz+1.82),(.385,.018,.61),(0,0,0)) for k in range(5)]
basecab=[('box',(9.96,11.02,fz+.43),(.59,.62,.84),(0,0,0))]
unit=pa._prims('PivotLaundryCabinetFactory(2102).spawn_asset(2102)',[(stone,parts),(steel,bowl),(oak,upper+fronts+basecab)]);unit['ir_room']='utility_0/0'
# Smooth curved gooseneck faucet, rather than a two-stick tap.
curve=bpy.data.curves.new('pivot_laundry_faucet','CURVE');curve.dimensions='3D';curve.bevel_depth=.012;curve.bevel_resolution=3
points=[(9.94,11.24,fz+.91),(9.94,11.24,fz+1.14)]+[(9.94,11.13+.11*math.cos(t),fz+1.14+.11*math.sin(t)) for t in [math.pi*i/16 for i in range(17)]]
spline=curve.splines.new('POLY');spline.points.add(len(points)-1)
for p,co in zip(spline.points,points):p.co=(*co,1)
tap=bpy.data.objects.new('PivotLaundryFaucetFactory(2103).spawn_asset(2103)',curve);bpy.context.scene.collection.objects.link(tap);curve.materials.append(steel);tap['ir_room']='utility_0/0'
fixes.append({'issue':'laundry reference requires two appliances; old run had one faceted washer and no dryer','action':'washer + dryer at real scale, oak upper/base storage, segmented stone counter and recessed sink, curved faucet within existing room'})
# Pantry has two usable counters. Keep the source garage doorway x17..17.9 free.
for o in list(bpy.data.objects):
 if o.get('ir_room')=='utility_0/1' and any(k in o.name for k in ('DrinkCansFactory','EspressoMachineFactory')):remove(o)
for o in bpy.data.objects:
 if o.type=='MESH' and o.get('ir_room')=='utility_0/1':
  for slot in o.material_slots:
   if slot.material and slot.material.name.startswith('ir_pantry_cab'):slot.material=oak
counter=pa._prims('PivotPantrySecondCounterFactory(2110).spawn_asset(2110)',[(oak,[('box',(19.30,9.43,fz+.43),(1.95,.51,.84),(0,0,0))]+[('box',(18.325+(k+.5)*1.95/4,9.70,fz+.43),(.472,.02,.78),(0,0,0)) for k in range(4)]),(stone,[('box',(19.30,9.44,fz+.89),(2.0,.56,.035),(0,0,0))])]);counter['ir_room']='utility_0/1'
shelf=pa._prims('PivotPantryOpenShelfFactory(2111).spawn_asset(2111)',[(oak,[('box',(19.3,9.30,z),(2.0,.28,.035),(0,0,0)) for z in (fz+1.45,fz+1.95)])]);shelf['ir_room']='utility_0/1'
for i,x in enumerate((18.55,18.9,19.25,19.6,19.95)):
 o=pa._prims(f'PivotPantryJarFactory({2120+i}).spawn_asset({2120+i})',[(white,[('cyl',(x,9.32,fz+1.59),(.07,.07,.23),(0,0,0))]),(oak,[('cyl',(x,9.32,fz+1.715),(.073,.073,.025),(0,0,0))])]);o['ir_room']='utility_0/1'
coffee=pa._prims('PivotHomeCoffeeMachineFactory(2130).spawn_asset(2130)',[(dark,[('box',(18.35,11.05,1.08754+.20),(.32,.30,.40),(0,0,0))]),(steel,[('box',(18.35,10.885,1.08754+.27),(.20,.035,.10),(0,0,0)),('box',(18.35,10.86,1.08754+.03),(.24,.13,.035),(0,0,0))]),(white,[('cyl',(18.35,10.86,1.08754+.10),(.037,.041,.10),(0,0,0))])]);coffee['ir_room']='utility_0/1'
fixes.append({'issue':'pantry reference has opposite oak worktops, not a single commercial-looking white run','action':'oak fronts, second counter/open shelves and neutral jars, compact domestic coffee machine; garage opening remains clear'})
# Entry console fits the south wall outside entrance/bedroom circulation.
console=pa._prims('PivotEntryConsoleFactory(2140).spawn_asset(2140)',[(oak,[('box',(22.8,14.72,fz+.78),(1.05,.32,.08),(0,0,0))]+[('box',(x,14.72,fz+.38),(.10,.29,.76),(0,0,0)) for x in (22.33,23.27)])]);console['ir_room']='hallway_0/0'
vase=pa._prims('PivotEntryVaseFactory(2141).spawn_asset(2141)',[(cloth,[('cyl',(22.8,14.72,fz+.92),(.075,.05,.20),(0,0,0))])]);vase['ir_room']='hallway_0/0'
# Very compact paired bedside tables in BED03, kept north of the wardrobe end.
for i,x in enumerate((5.29,6.95)):
 ns=pa._prims(f'PivotBed03SideFactory({2150+i}).spawn_asset({2150+i})',[(oak,[('box',(x,20.25,fz+.26),(.23,.38,.50),(0,0,0))]),(cloth,[('cyl',(x,20.25,fz+.78),(.075,.06,.16),(0,0,0))]),(steel,[('cyl',(x,20.25,fz+.62),(.01,.01,.20),(0,0,0))])]);ns['ir_room']='bedroom_0/1'
fixes.append({'issue':'empty entry and BED03 missing bedside function','action':'entry console/vase outside paths; two compact BED03 nightstands/lamps clear of wardrobe'})
bpy.context.view_layer.update();invalid=[o.name for o in bpy.data.objects if o.type=='MESH' and any(not math.isfinite(v) or abs(v)>100 for v in o.dimensions)];assert not invalid,invalid
bpy.context.scene['pivot_revision']='r16_utility_programme';bpy.ops.wm.save_as_mainfile(filepath=str(run/'scene_review_r16.blend'))
(base/'revision_r16.json').write_text(json.dumps({'fixes':fixes,'invalid_mesh_extents':invalid,'camera_changes':[],'camera_count':28,'limitations':['WIR remains one-sided because retaining source room depth with two full-depth wardrobe rows would block circulation','Original screenshot dimensions and cropped carport remain uncertain']},indent=2));print('PIVOT_R16_COMPLETE',flush=True)
