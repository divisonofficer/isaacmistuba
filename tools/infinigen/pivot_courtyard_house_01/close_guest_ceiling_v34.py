"""Continuous interior ceiling liner for the visible guest-bedroom door-head void."""
import bpy,json,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
ceiling=bpy.data.objects['bedroom_0/4.ceiling'];corners=[ceiling.matrix_world@Vector(v) for v in ceiling.bound_box];z=min(p.z for p in corners)
assert 2.6<z<3.1,(z,[list(v) for v in corners])
bpy.context.view_layer.update()
def probe():
    dg=bpy.context.evaluated_depsgraph_get();rows=[]
    for x in (20.16,20.30,20.6,21.0):
        for y in (.16,.35,.65,.95,1.2):
            hit,p,n,f,o,m=bpy.context.scene.ray_cast(dg,Vector((x,y,z-.25)),Vector((0,0,1)),distance=.5)
            rows.append({'xy':[x,y],'hit':o.name if o else None,'z':p.z if hit else None})
    return rows
before=probe()
m=bpy.data.materials.new('guest_v34_continuous_ceiling_plaster');m.use_nodes=True;bs=m.node_tree.nodes['Principled BSDF'];bs.inputs['Base Color'].default_value=(.72,.70,.66,1);bs.inputs['Roughness'].default_value=.85
o=pa._prims('PivotGuestV34_continuous_ceiling_liner',[(m,[('box',(21.75,2,z-.006),(3.22,3.72,.012),(0,0,0))])]);o['ir_room']='bedroom_0/4';o['ir_role']='continuous_interior_ceiling_liner'
bpy.context.view_layer.update();after=probe()
assert all(row['hit']=='PivotGuestV34_continuous_ceiling_liner' for row in after if row['xy'][0]>.20+20),after
# The first sample column passes through the existing solid door casing below
# the ceiling. It must remain a valid nearer hit rather than a false failure.
assert all(row['hit'] and (row['hit']=='PivotGuestV34_continuous_ceiling_liner' or row['hit'].startswith('DoorCasingFactory')) for row in after),after
bpy.context.scene['pivot_revision']='quality_rework_v34_guest_ceiling_candidate';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v34.blend'))
(B/'guest_ceiling_v34.json').write_text(json.dumps({'status':'liner_saved_same_camera_visual_review_pending','source_scene':'scene_rework_integrated_v33.blend','original_ceiling_underside_z':z,'liner_thickness_m':.012,'before_upward_rays':before,'after_upward_rays':after,'remaining':['Original guest bedroom camera must show no black gap','Verify ceiling fixtures remain exposed and room dimensions preserved','Latest full-scene consistency']},ensure_ascii=False,indent=2)+'\n');print('PIVOT_GUEST_CEILING_V34_SAVED',z,flush=True)
