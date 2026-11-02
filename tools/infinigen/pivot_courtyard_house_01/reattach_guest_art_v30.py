"""Reattach both artworks whose north wall was replaced with courtyard glazing."""
import bpy, math, json
from pathlib import Path
from mathutils import Vector, Matrix
R=Path(__file__).resolve().parents[3]
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
rows=[]
for name,x in [('WallArtFactory(8242972).spawn_asset(20)',14.4),('WallArtFactory(8242973).spawn_asset(21)',16.1)]:
    o=bpy.data.objects[name]
    corners=[o.matrix_world@Vector(v) for v in o.bound_box]
    old=sum(corners,Vector())/8
    target=Vector((x,.174,1.80))
    o.matrix_world=Matrix.Translation(target)@Matrix.Rotation(math.pi,4,'Z')@Matrix.Translation(-old)@o.matrix_world
    o['ir_room']='living-room_0/2'
    o['support_rework']='south opaque wall; moved off new north glazing'
    bpy.context.view_layer.update()
    corners=[o.matrix_world@Vector(v) for v in o.bound_box]
    center=sum(corners,Vector())/8
    # Ray starts just behind the picture and must reach actual opaque room wall.
    origin=Vector((center.x,min(v.y for v in corners)-.002,center.z))
    hit,p,n,face,obj,mat=bpy.context.scene.ray_cast(bpy.context.evaluated_depsgraph_get(),origin,Vector((0,-1,0)),distance=.30)
    proof={'hit_object':obj.name if obj else None,'hit_point':list(p),'from_picture_back':list(origin)}
    assert hit and obj.name.startswith('living-room_0/2'),proof
    rows.append({'object':name,'old_center':list(old),'new_center':list(center),'wall_support_ray':proof})
bpy.context.scene['pivot_revision']='quality_rework_v30_guest_art_candidate'
bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v30.blend'))
(B/'guest_art_support_v30.json').write_text(json.dumps({'status':'wall_support_verified_visual_review_pending','source_scene':'scene_rework_integrated_v29.blend','changes':rows,'remaining':['Guest living view: no art suspended in glazing','Courtyard view: glazing clear and art against actual wall','Whole-scene final regression and registration']},ensure_ascii=False,indent=2)+'\n')
print('PIVOT_GUEST_ART_V30_SAVED',json.dumps(rows),flush=True)
