"""Replace solid upper cabinet filler with a manufactured hollow carcass.

Keep six existing doors, textures, lighting and external envelope unchanged.
"""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[3]
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
src=base/'scene_candidate_r50.blend';out=base/'scene_candidate_r51.blend'
assert not out.exists(),out
sha=hashlib.sha256(src.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(src))
old=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_upper')
pts=[old.matrix_world@Vector(c) for c in old.bound_box]
lo=Vector([min(p[i] for p in pts) for i in range(3)])
hi=Vector([max(p[i] for p in pts) for i in range(3)])
mat=old.data.materials[0];collection=old.users_collection[0]
t=.018;rows=[]
def panel(name,a,b):
    a,b=Vector(a),Vector(b)
    bpy.ops.mesh.primitive_cube_add(size=1,location=(a+b)/2)
    o=bpy.context.object;o.name='R51_upper_'+name;o.dimensions=b-a
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    for c in list(o.users_collection):c.objects.unlink(o)
    collection.objects.link(o);o.data.materials.append(mat)
    o['program_key']='coffee_upper';o['carcass_part']=name
    bevel=o.modifiers.new('Manufactured_edge_radius','BEVEL');bevel.width=.0008;bevel.segments=3
    o.modifiers.new('Planar_normals','WEIGHTED_NORMAL')
    rows.append({'object':o.name,'part':name,'lo':list(a),'hi':list(b)})
x0,y0,z0=lo;x1,y1,z1=hi
panel('bottom',(x0,y0,z0),(x1,y1,z0+t))
panel('top',(x0,y0,z1-t),(x1,y1,z1))
panel('left',(x0,y0,z0+t),(x1,y0+t,z1-t))
panel('right',(x0,y1-t,z0+t),(x1,y1,z1-t))
panel('back',(x1-.009,y0+t,z0+t),(x1,y1-t,z1-t))
# Internal dividers sit behind the door joints, leaving a physical reveal.
doors=sorted([o for o in bpy.data.objects if o.get('program_key')=='coffee_upper_front'],key=lambda o:o.location.y)
assert len(doors)==6
for i in range(1,6):
    yy=y0+(y1-y0)*i/6
    panel('divider_'+str(i),(x0+.025,yy-t/2,z0+t),(x1-.009,yy+t/2,z1-t))
bpy.data.objects.remove(old,do_unlink=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out))
assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r51.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'scope':'Upper cabinet carcass only; six doors, all shaders and lights unchanged','external_bounds':[list(lo),list(hi)],'panels':rows,'photorealism_accepted':False,'requires':'Same-camera wide comparison; verify gap depth, no new light leaks or detached panels'},indent=2))
print('SAVED',out,flush=True)
