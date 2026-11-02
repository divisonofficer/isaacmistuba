"""Support/contact fixes discovered during r13-r14 direct review."""
import bpy,bmesh,json,math,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
pa.SURFACE_DETAIL=False
base=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';run=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full';fixes=[]
def bounds(o):
 pts=[o.matrix_world@Vector(v) for v in o.bound_box]
 return [(min(v[i] for v in pts),max(v[i] for v in pts)) for i in range(3)]
# Actual dining furniture was at y~15.96, not the requested plan point y14.25.
# Derive the support from the realised table mesh, never from intended placement.
table=next(o for o in bpy.data.objects if o.get('ir_room')=='dining-room_0/0' and 'TableDiningFactory' in o.name)
b=bounds(table);cx,cy=(b[0][0]+b[0][1])/2,(b[1][0]+b[1][1])/2
vase=bpy.data.objects['PivotTableVaseFactory(1521).spawn_asset(1521)'];vb=bounds(vase);old=Vector(((vb[0][0]+vb[0][1])/2,(vb[1][0]+vb[1][1])/2,vb[2][0]))
delta=Vector((cx,cy,b[2][1]+.002))-old
flowers=[o for o in bpy.data.objects if o.get('pivot_dressing') and o!=vase and not o.name.startswith('PivotTableVaseFactory') and (Vector((o.location.x,o.location.y,0))-Vector((old.x,old.y,0))).length<.3]
vase.location+=delta
for o in flowers:o.location+=delta
fixes.append({'issue':'dining vase/flower floated at planned position rather than realised table','action':'move both to actual table centre and top height','translation':list(delta),'table':table.name,'table_top_z':b[2][1]})
# Seat study book components on actual shelf planes; add a recessed plinth.
book=bpy.data.objects['PivotStudyBooksFactory(1604).spawn_asset(1604)'];bm=bmesh.new();bm.from_mesh(book.data);seen=set();adjusted=0
for v in bm.verts:
 if v in seen:continue
 comp=[];todo=[v];seen.add(v)
 while todo:
  cur=todo.pop();comp.append(cur)
  for e in cur.link_edges:
   other=e.other_vert(cur)
   if other not in seen:seen.add(other);todo.append(other)
 lo=min(v.co.z for v in comp);hi=max(v.co.z for v in comp)
 target=.2095 if .20<lo<.36 and hi<.52 else (.5695 if .58<lo<.73 and hi<.94 else (1.5695 if 1.55<lo<1.65 else None))
 if target is not None:
  for v in comp:v.co.z+=target-lo
  adjusted+=1
bm.to_mesh(book.data);bm.free();book.data.update()
oak=bpy.data.materials['pivot_r13_reference_oak'];pa._prims('PivotStudyPlinthFactory(2001).spawn_asset(2001)',[(oak,[('box',(22.25,9.36,.1575),(2.55,.32,.025),(0,0,0))])])
monitor=next(o for o in bpy.data.objects if 'PivotCleanMonitorFactory' in o.name);monitor.data=monitor.data.copy()
for v in monitor.data.vertices:v.co.z-=.0375
monitor.data.update()
# Engine bed platform mesh starts 4cm above its origin. Recessed supports make
# the frame physically grounded without altering its visible bedding geometry.
supportmat=pa._flat('pivot_r15_recessed_support',(.06,.045,.03),.9)
for i,bed in enumerate([o for o in bpy.data.objects if o.parent is None and o.get('ir_room') and 'SoftBedFactory' in o.name]):
 o=pa._prims(f'PivotBedPlinthFactory({2010+i}).spawn_asset({2010+i})',[(supportmat,[('box',(1.1,0,.025),(1.9,1.5,.05),(0,0,0))])]);o.parent=bed;o['ir_room']=bed['ir_room']
# Newly spawned bathroom factories may reuse old cached chrome names.
steel=bpy.data.materials['pivot_r14_brushed_hardware']
for o in bpy.data.objects:
 if o.type=='MESH':
  for slot in o.material_slots:
   if slot.material and slot.material.name=='ir_chrome':slot.material=steel
bpy.context.view_layer.update();vb=bounds(vase);assert abs(vb[2][0]-b[2][1]-.002)<1e-4,(vb,b)
assert b[0][0]<vb[0][0]<vb[0][1]<b[0][1] and b[1][0]<vb[1][0]<vb[1][1]<b[1][1]
fixes.append({'issue':'book and display support gaps, native bed platform modelling clearance','action':'seat books/display and add recessed case/bed plinths; clean reused chrome','book_components_adjusted':adjusted})
invalid=[o.name for o in bpy.data.objects if o.type=='MESH' and any(not math.isfinite(v) or abs(v)>100 for v in o.dimensions)];assert not invalid,invalid
bpy.context.scene['pivot_revision']='r15_support_contacts';bpy.ops.wm.save_as_mainfile(filepath=str(run/'scene_review_r15.blend'))
(base/'revision_r15.json').write_text(json.dumps({'fixes':fixes,'invalid_mesh_extents':invalid,'dining_vase_bounds':vb,'dining_table_bounds':b,'camera_changes':[],'camera_count':28},indent=2));print('PIVOT_R15_COMPLETE',flush=True)
