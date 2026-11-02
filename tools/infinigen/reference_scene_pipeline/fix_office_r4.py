"""Native exterior meshes are open sheets; remove faces without closing caps."""
import json
from pathlib import Path
import sys
import bpy
from mathutils import Vector
from cut_surface import remove_box_faces
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r2.blend'))
dark=pa._flat('office02_casing_charcoal',(.025,.03,.035),.45)
for o in bpy.data.objects:
    if o.type=='MESH' and 'DoorCasingFactory' in o.name:
        for slot in o.material_slots:slot.material=dark
shells=[o for o in bpy.data.objects if o.type=='MESH' and o.name.endswith(('.wall','.exterior'))]
cuts=[((4,4.915+i*2.5,1.53),(.75,.97,2.4)) for i in range(6)]
for lo,hi in [(.95,5.85),(6.15,9.85),(10.15,14.4)]:cuts.append((((lo+hi)/2,18,1.53),(hi-lo,.75,2.4)))
changes=[]
for loc,size in cuts:
    for wall in shells:
        pts=[wall.matrix_world@Vector(v) for v in wall.bound_box]
        if all(max(v[k] for v in pts)>=loc[k]-size[k]/2 and min(v[k] for v in pts)<=loc[k]+size[k]/2 for k in range(3)):
            n=remove_box_faces(wall,loc,size)
            if n:changes.append({'object':wall.name,'deleted_faces':n})
bpy.context.view_layer.update()
# Ray stack must cross clear glass but no opaque native sheet in the aperture.
deps=bpy.context.evaluated_depsgraph_get();raychecks=[]
for x in [2.5,8.8,12.5]:
    origin=Vector((x,17.5,1.4));direction=Vector((0,1,0));hits=[]
    for _ in range(8):
        h,p,n,i,o,m=bpy.context.scene.ray_cast(deps,origin,direction,distance=5)
        if not h:break
        if 17.5<p.y<18.5:hits.append(o.name)
        origin=p+direction*.004
    raychecks.append({'x':x,'aperture_hits':hits,'opaque_shell_blocker':any(n.endswith(('.wall','.exterior')) for n in hits)})
assert not any(r['opaque_shell_blocker'] for r in raychecks),raychecks
out=base/'scene_candidate_r4.blend';bpy.ops.wm.save_as_mainfile(filepath=str(out))
(base/'correction_r4.json').write_text(json.dumps({'reason':'Boolean of open shell produced closing caps; plane-split face removal used instead','changes':changes,'ray_checks':raychecks,'visual_acceptance':False},indent=2))
