"""Repair the reversed interior wall triangle identified by pixel-direction rays."""
import bpy,bmesh,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
o=bpy.data.objects['bedroom_0/4.wall'];o.data=o.data.copy();bm=bmesh.new();bm.from_mesh(o.data);bm.normal_update();bad=[];records=[]
for face in bm.faces:
    p=o.matrix_world@face.calc_center_median();n=o.matrix_world.to_3x3()@face.normal
    if abs(p.x-20.145542)<.003 and .14<p.y<3.86 and n.x<-.9:
        bad.append(face);records.append({'center':list(p),'old_world_normal':list(n),'vertices':len(face.verts)})
assert bad,'Expected reversed interior wall triangle was not found'
bmesh.ops.reverse_faces(bm,faces=bad);bm.normal_update();bm.to_mesh(o.data);bm.free()
# The failed ceiling liner did not address the wall normal; restore the original ceiling.
liner=bpy.data.objects.get('PivotGuestV34_continuous_ceiling_liner')
if liner:bpy.data.objects.remove(liner,do_unlink=True)
m=bpy.data.materials['garage_v33_fine_mottled_concrete']
for node in m.node_tree.nodes:
    if node.type=='VALTORGB':
        node.color_ramp.elements[0].color=(.255,.265,.265,1)
        node.color_ramp.elements[1].color=(.325,.335,.325,1)
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v35_wall_normal_candidate';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v35.blend'))
(B/'guest_wall_normal_v35.json').write_text(json.dumps({'status':'saved_same_camera_visual_review_pending','source_scene':'scene_rework_integrated_v34.blend','diagnostic':'guest_gap_diagnostic.log: black triangle pixels hit bedroom west wall face 77 with outward -X normal, unlike adjacent interior +X faces. Ceiling rays were not missing.','reversed_interior_faces':records,'removed_failed_ceiling_liner':bool(liner),'secondary_change':'Reduced garage concrete mottling contrast; retained fine roughness and surface grain','remaining':['Guest-bedroom same camera must show no black triangle','Garage same camera surface balance','Latest physical audit and complete final render/report registration consistency']},ensure_ascii=False,indent=2)+'\n');print('PIVOT_GUEST_NORMAL_V35_SAVED',records,flush=True)
