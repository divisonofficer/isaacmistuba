"""Direct reference inventory corrections: two study desks, storage, lounge seats."""
import bpy,json,sys,math
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner.proc_home import BalconyChairFactory,RecessedSpotFactory
pa.SURFACE_DETAIL=False
base=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';run=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full';fixes=[]
def mat(name,col,rough=.8):
 m=bpy.data.materials.new(name);m.use_nodes=True;bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(*col,1);bs.inputs['Roughness'].default_value=rough;return m

def bounds(o):
 pts=[o.matrix_world@Vector(v) for v in o.bound_box]
 return [(min(v[i] for v in pts),max(v[i] for v in pts)) for i in range(3)]
def align(o,x,y,z):
 bpy.context.view_layer.update();b=bounds(o);o.location+=Vector((x-(b[0][0]+b[0][1])/2,y-(b[1][0]+b[1][1])/2,z-b[2][0]))
# The actual study reference has TWO desks. Previous single-desk interpretation
# was wrong; keep this correction in the round record rather than hiding it.
desk=next(o for o in bpy.data.objects if o.get('ir_room')=='office_0/0' and 'OfficeDeskFactory' in o.name)
monitor=next(o for o in bpy.data.objects if 'PivotCleanMonitorFactory' in o.name)
desk.rotation_euler.z=0;align(desk,21.05,10.85,.14754)
second=desk.copy();second.data=desk.data.copy();bpy.context.scene.collection.objects.link(second);second.name='PivotSecondStudyDeskFactory(1601).spawn_asset(1601)';second.rotation_euler.z=math.pi;align(second,23.45,10.85,.14754);second['ir_room']='office_0/0'
monitor.matrix_world=second.matrix_world.copy()
chair=next(o for o in bpy.data.objects if o.get('ir_room')=='office_0/0' and 'OfficeChairFactory' in o.name)
chair.rotation_euler.z=math.pi;align(chair,21.6,10.85,.14754)
chair2=chair.copy();chair2.data=chair.data.copy();bpy.context.scene.collection.objects.link(chair2);chair2.name='PivotSecondStudyChairFactory(1602).spawn_asset(1602)';chair2.rotation_euler.z=0;align(chair2,22.9,10.85,.14754);chair2['ir_room']='office_0/0'
oak=pa._flat('pivot_r13_reference_oak',(.48,.34,.22),.6,wood=True);paper=mat('pivot_r13_book_pages',(.70,.66,.55));cream=mat('pivot_r13_cream',(.64,.61,.53));dark=mat('pivot_r13_charcoal',(.025,.03,.035),.6);sage=mat('pivot_r13_sage',(.24,.29,.22));taupe=mat('pivot_r13_taupe',(.38,.32,.25))
# Low 3-bay bookcase, shelves/cabinet above left desk, books and two baskets.
frame=[]
for z in (.19,.55,.94):frame.append(('box',(22.25,9.36,z),(2.55,.34,.035),(0,0,0)))
for x in (20.96,21.82,22.68,23.54):frame.append(('box',(x,9.36,.56),(.035,.34,.78),(0,0,0)))
frame.append(('box',(22.25,9.205,.56),(2.6,.025,.80),(0,0,0)))
frame.extend([('box',(20.83,10.85,2.0),(.32,1.75,.52),(0,0,0)),('box',(20.96,10.85,1.55),(.36,1.75,.035),(0,0,0))])
shelf=pa._prims('PivotStudyStorageFactory(1603).spawn_asset(1603)',[(oak,frame)]);shelf['ir_room']='office_0/0'
books=[];pages=[]
for row,z in enumerate((.37,.75)):
 for bay,x0 in enumerate((21.10,21.96,22.82)):
  for k in range(4):
   x=x0+.09*k;h=.20+.025*((k+bay)%3);books.append(('box',(x,9.37,z),(.065,.21,h),(0,0,.04*(k%2))));pages.append(('box',(x+.002,9.38,z+.003),(.05,.19,h-.022),(0,0,.04*(k%2))))
# Books on the overhead shelf.
for k in range(6):books.append(('box',(20.97,10.35+k*.12,1.70),(.21,.07,.27),(0,0,0)))
book=pa._prims('PivotStudyBooksFactory(1604).spawn_asset(1604)',[(taupe,books),(paper,pages)]);book['ir_room']='office_0/0'
for i,x in enumerate((21.55,23.25)):
 o=pa._prims(f'PivotStudyBasketFactory({1605+i}).spawn_asset({1605+i})',[(cream,[('box',(x,9.35,.34),(.30,.24,.23),(0,0,0))])]);o['ir_room']='office_0/0'
# Closed laptop on the left desk; right desk retains the clean monitor.
laptop=pa._prims('PivotClosedLaptopFactory(1607).spawn_asset(1607)',[(dark,[('box',(.08,0,.78),(.33,.44,.022),(0,0,0))])]);laptop.matrix_world=desk.matrix_world.copy();laptop['ir_room']='office_0/0'
rug=pa._prims('PivotStudyRugFactory(1608).spawn_asset(1608)',[(cream,[('box',(22.25,10.85,.151),(1.05,2.25,.008),(0,0,0))])]);rug['ir_room']='office_0/0'
# Two pen cups on usable desk corners, clear of monitor and laptop.
for i,ds in enumerate((desk,second)):
 cup=pa._prims(f'PivotStudyPenCupFactory({1610+i}).spawn_asset({1610+i})',[(cream,[('cyl',(.15,.52,.82),(.045,.045,.12),(0,0,0))]),(dark,[('cyl',(.15+d,.52,.92),(.003,.003,.20),(0,.08,0)) for d in (-.015,0,.015)])]);cup.matrix_world=ds.matrix_world.copy();cup['ir_room']='office_0/0'
fixes.append({'issue':'study reference was misread as one workstation','action':'corrected to 2 opposite oak desks / 2 chairs / 1 monitor + closed laptop, low bookcase, overhead cabinet/shelf, book groups, baskets, pen cups and rug','basis':'study_v1.png directly reread; r8 inventory used only as cross-check'})
# Living ref: two sofas AND two chairs by the glazing, plus loose cushions.
BalconyChairFactory.TEAL=(.43,.41,.36)
for i,x in enumerate((17.5,18.9)):
 o=BalconyChairFactory(48713300+i).spawn_asset(1620+i);o.rotation_euler.z=-math.pi/2;align(o,x,16.02,.14754);o['ir_room']='living-room_0/1'
small=pa._prims('PivotWindowSideTableFactory(1622).spawn_asset(1622)',[(oak,[('cyl',(18.2,16.02,.14754+.22),(.17,.17,.44),(0,0,0))])]);small['ir_room']='living-room_0/1'
for j,(c,sz,rot) in enumerate([((x,12.00,.14754+.68),(.42,.16,.40),(-.18,0,.07*(i-1))) for i,x in enumerate((17.12,18.0,18.84))]+[((16.02,y,.14754+.68),(.16,.42,.40),(0,.18,.08*(i-1))) for i,y in enumerate((14.0,14.75,15.5))]):
 o=pa._prims(f'PivotLivingCushionFactory({1630+j}).spawn_asset({1630+j})',[(sage if j%3==0 else cream,[('rbox',c,sz,rot)])]);o['ir_room']='living-room_0/1'
fixes.append({'issue':'living reference seating inventory incomplete','action':'2 native window armchairs, small side table, 6 loose cushions; existing 2 sofas preserved'})
# Actual external soil plane was 13.5 cm below tree roots; raise turf beneath
# roots while remaining below interior floor and deck surface.
ground=next(o for o in bpy.data.objects if 'PivotExternalGroundFactory' in o.name);ground.location.z+=.195
fixes.append({'issue':'apparent floating external tree bases','action':'raise exterior ground top from -0.075m to 0.12m; roots at about 0.06m now seated in soil; floor at 0.145m remains above turf'})
# Modest recessed geometry matches the references, while preserving real lights.
for i,(x,y) in enumerate([(16.5,13.0),(19.5,13.0),(16.5,15.8),(19.5,15.8),(12.0,12.5),(14.0,15.5),(21.2,10.0),(23.2,12.0)]):
 spot=RecessedSpotFactory().spawn_asset(1640+i);spot.location=(x,y,2.65)
views=json.loads((run/'review_views_r12.json').read_text())
for v in views:
 if v['name']=='office_0-0_wide1':v.update(location=[22.25,12.65,1.65],target=[22.25,10.15,1.1],hfov=85)
(run/'review_views_r13.json').write_text(json.dumps(views,indent=2))
bpy.context.view_layer.update();invalid=[o.name for o in bpy.data.objects if o.type=='MESH' and any(not math.isfinite(v) or abs(v)>100 for v in o.dimensions)];assert not invalid,invalid
# Clear middle study corridor between chair bounding boxes at seat level.
cb1,cb2=bounds(chair),bounds(chair2);assert cb2[0][0]-cb1[0][1]>.55,(cb1,cb2)
bpy.context.scene['pivot_revision']='r13_inventory_reference_fit';bpy.ops.wm.save_as_mainfile(filepath=str(run/'scene_review_r13.blend'))
(base/'revision_r13.json').write_text(json.dumps({'fixes':fixes,'invalid_mesh_extents':invalid,'study_chair_gap_m':cb2[0][0]-cb1[0][1],'study_desks':[bounds(desk),bounds(second)],'camera_changes':['office_0-0_wide1'],'camera_count':len(views)},indent=2));print('PIVOT_R13_COMPLETE',flush=True)
