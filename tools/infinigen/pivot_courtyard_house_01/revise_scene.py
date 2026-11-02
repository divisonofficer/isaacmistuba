"""Direct fixes from furnished overview, mesh audit and reference comparison."""
import argparse
import json
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/infinigen'))
import furnish_rooms as fr
import room_dressing as rd
from room_planner import proc_assets as pa
from room_planner.proc_home import OakWardrobeFactory, BalconyTableFactory, BalconyChairFactory

p=argparse.ArgumentParser();p.add_argument('blend');p.add_argument('--out',required=True);a=p.parse_args()
bpy.ops.wm.open_mainfile(filepath=a.blend)
fixes=[]

def remove_family(o):
 for x in reversed([o,*o.children_recursive]):bpy.data.objects.remove(x,do_unlink=True)

def clone_family(o):
 originals=[o,*o.children_recursive];copies={}
 for x in originals:
  c=x.copy()
  if x.type=='MESH':c.data=x.data.copy()
  bpy.context.scene.collection.objects.link(c);copies[x]=c
 for x,c in copies.items():
  c.parent=copies.get(x.parent);c.matrix_parent_inverse=x.matrix_parent_inverse.copy();c.matrix_basis=x.matrix_basis.copy()
  c['ir_room']='bedroom_0/1';c['pivot_repaired']=True
  c.name='PivotRepair_'+x.name
 return copies[o]

bad=[o for o in bpy.data.objects if o.type=='MESH' and any(abs(v)>100 for v in o.dimensions)]
assert len(bad)==1 and 'BedFactory' in bad[0].name,[(o.name,list(o.dimensions)) for o in bad]
healthy=next(o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith('BedFactory') and o.get('ir_room')=='bedroom_0/0')
old_name=bad[0].name;remove_family(bad[0])
for o in list(bpy.data.objects):
 if o.get('ir_room')=='bedroom_0/1' and o.parent is None and 'Nightstand' in o.name:remove_family(o)
bed=clone_family(healthy)
room=fr.Room('bedroom_0/1',rd._rooms()['bedroom_0/1'],bpy.context.scene,bpy.context.evaluated_depsgraph_get())
assert fr._place(bed,6.0,19.5,-math.pi/2,room,[],(1,0)), 'replacement bed must stand on actual floor'
fixes.append({'issue':'exploded bed geometry','old_object':old_name,'old_height_m':43719.6875,
              'action':'clone healthy native bed family and place within BED03 floor','new_bounds':fr.footprint(bed)})
robe=OakWardrobeFactory(48712501).spawn_asset(701);robe.scale.y*=2.0/robe.dimensions.y
bpy.context.view_layer.update()
assert fr._place(robe,7.5,18.8,math.pi,room,[fr.footprint(bed)],(1,0)), 'robe must clear bed and floor'
robe['ir_room']='bedroom_0/1';fixes.append({'issue':'dropped wardrobe','action':'2 m fitted wardrobe along east wall'})

linen=pa._flat('pivot_neutral_linen',(.72,.68,.60),.95)
white=pa._flat('pivot_neutral_mattress',(.85,.83,.77),.95)
muted=0
for o in bpy.data.objects:
 if o.type=='MESH' and any(k in o.name for k in ('BlanketFactory','BoxComforterFactory','MattressFactory','PillowFactory','TowelFactory')):
  o.data=o.data.copy();o.data.materials.clear();o.data.materials.append(white if 'MattressFactory' in o.name else linen);muted+=1
fixes.append({'issue':'bright mismatching bedding','action':'neutral warm linen materials','mesh_count':muted})

# The guest suite needs meals seating more than a second coffee table. Keep the
# sofa and kitchenette, replace the central coffee table with a compact set.
for o in list(bpy.data.objects):
 if o.get('ir_room')=='living-room_0/2' and o.parent is None and 'coffee' in o.name.lower():remove_family(o)
guest=fr.Room('living-room_0/2',rd._rooms()['living-room_0/2'],bpy.context.scene,bpy.context.evaluated_depsgraph_get())
tab=BalconyTableFactory(701).spawn_asset(701);tab.scale.x*=.8;tab.scale.y*=.8
assert fr._place(tab,15.6,1.8,0,guest,[],(1,0))
tab['ir_room']='living-room_0/2'
BalconyChairFactory.TEAL=(.35,.34,.31)
for i,(x,y,yaw) in enumerate([(14.75,1.8,0),(16.45,1.8,math.pi)]):
 o=BalconyChairFactory(702+i).spawn_asset(702+i)
 assert fr._place(o,x,y,yaw,guest,[],(1,0))
 o['ir_room']='living-room_0/2'
fixes.append({'issue':'dropped guest meals set','action':'replace coffee table with compact native table and two chairs'})

# Source shows a bathtub in the shared bathroom; a separate cubicle would crowd
# the doorway. Use a shower over the tub, within its existing floor footprint.
tub=next(o for o in bpy.data.objects if 'BathtubFactory' in o.name and o.get('ir_room')=='bathroom_0/0')
b=fr.footprint(tub);z=fr.Room('bathroom_0/0',rd._rooms()['bathroom_0/0'],bpy.context.scene,bpy.context.evaluated_depsgraph_get()).z
chrome=pa._flat('pivot_shower_chrome',(.7,.72,.75),.2,1)
x,y=b[1]-.12,b[3]-.25
rail=pa._prims('PivotBathShowerFactory(701).spawn_asset(701)',[(chrome,[
 ('cyl',(x,y,z+.9),(.025,.025,1.9),(0,0,0)),
 ('cyl',(x-.18,y,z+1.86),(.18,.025,.025),(0,0,0)),
 ('cyl',(x-.35,y,z+1.82),(.10,.10,.035),(0,0,0))])])
rail['ir_room']='bathroom_0/0'
fixes.append({'issue':'separate shower cubicle dropped','action':'shared bathroom revised to a bath/shower combination to preserve circulation'})

bpy.context.view_layer.update()
invalid=[(o.name,list(o.dimensions)) for o in bpy.data.objects if o.type=='MESH' and any(not math.isfinite(v) or abs(v)>100 for v in o.dimensions)]
assert not invalid,invalid
bpy.context.scene['pivot_revision']='r2_direct_review'
bpy.ops.wm.save_as_mainfile(filepath=a.out)
Path(a.out).with_suffix('.review.json').write_text(json.dumps({'fixes':fixes,'invalid_geometry':invalid},indent=2))
print('PIVOT_REVISION',json.dumps(fixes),flush=True)
