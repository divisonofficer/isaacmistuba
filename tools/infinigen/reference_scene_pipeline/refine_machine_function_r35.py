"""Add recognisable functional assembly: group head/filter, wand joint/grip, real drainage gaps."""
import bpy,bmesh,json,hashlib
from pathlib import Path
from mathutils import Vector
from material_detail import material
from detail_primitives import box,rod,tube,front_text,mark
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';source=base/'scene_candidate_r34.blend';out=base/'scene_candidate_r35.blend';assert not out.exists();sha=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));body=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_machine');x=body.location.x-.09;y=body.location.y;z0=body.location.z-.155;steel=material('MachineR35_brushed_hardware',(.55,.56,.57),.27,1)[0];black=material('MachineR35_heat_resistant_grip',(.012,.014,.016),.68)[0];printmat=material('MachineR35_panel_etch',(.07,.075,.08),.45)[0];created=[]
for o in list(bpy.data.objects):
 if o.get('program_key') in ['machine_spout','machine_drain_slot']:bpy.data.objects.remove(o,do_unlink=True)
# Header supports the brew group; removable filter locks into its ring.
created.append(rod('machine_brew_group',(x-.09,y,z0+.225),(x-.09,y,z0+.270),.036,steel).name)
created.append(rod('machine_filter_basket',(x-.09,y,z0+.208),(x-.09,y,z0+.228),.0305,steel).name)
rod('machine_filter_handle_core',(x-.09,y,z0+.218),(x-.155,y,z0+.218),.005,steel);rod('machine_filter_handle_grip',(x-.15,y,z0+.218),(x-.28,y,z0+.218),.010,black)
for side in [-1,1]:tube('machine_brew_spout_'+str(side),[(x-.09,y+side*.010,z0+.208),(x-.125,y+side*.012,z0+.192),(x-.13,y+side*.012,z0+.175)],.0035,steel)
# An articulated wand has a ball joint, safe grip and an identifiable end piece.
wand=next(o for o in bpy.data.objects if o.get('program_key')=='machine_steam_wand');coords=[wand.matrix_world@Vector(p.co[:3]) for p in wand.data.splines[0].points];root=coords[0];bm=bmesh.new();bmesh.ops.create_uvsphere(bm,u_segments=32,v_segments=16,radius=.012);me=bpy.data.meshes.new('machine_wand_ball');bm.to_mesh(me);bm.free();me.materials.append(steel)
for f in me.polygons:f.use_smooth=True
o=bpy.data.objects.new('machine_wand_ball_joint',me);bpy.context.scene.collection.objects.link(o);o.location=root;mark(o,'machine_wand_ball_joint');axis=(coords[1]-coords[0]).normalized();rod('machine_wand_safe_grip',root+axis*.025,root+axis*.065,.0075,black)
end=coords[-1];direction=(coords[-1]-coords[-2]).normalized();rod('machine_wand_tip',end-direction*.016,end,.0052,steel)
# Recessed sump with a separate slotted cover. Slots are actual gaps between metal strips.
tray=next(o for o in bpy.data.objects if o.get('program_key')=='machine_driptray');bpy.data.objects.remove(tray,do_unlink=True);box('machine_driptray',(x-.11,y,z0+.0035),(.27,.38,.002),steel,.0004)
for yy in [-.1875,.1875]:box('machine_sump_side',(x-.11,y+yy,z0+.0175),(.27,.005,.026),steel,.0004)
for xx in [-.2425,.0225]:box('machine_sump_end',(x+xx,y,z0+.0175),(.005,.37,.026),steel,.0004)
grate_z=z0+.031
for k in range(17):box('machine_grate_bar_'+str(k),(x-.11,y-.16+k*.02,grate_z),(.23,.016,.0018),steel,.00035)
for yy in [-.18,.18]:box('machine_grate_side_frame',(x-.11,y+yy,grate_z),(.25,.020,.002),steel,.0005)
for xx in [-.235,.015]:box('machine_grate_end_frame',(x+xx,y,grate_z),(.020,.34,.002),steel,.0005)
for index,label in enumerate(['POWER','BREW','STEAM']):front_text('machine_control_label_'+label,label,(x-.194, y+(.06-index*.06),z0+.303),.0035,printmat)
# A service seam/fasteners support product manufacture, with no real brand.
for yy in [-.175,.175]:rod('machine_front_panel_fastener',(x-.194, y+yy,z0+.29),(x-.195,y+yy,z0+.29),.0025,steel)
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r35.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'source_sha256':sha,'trigger':'Independent r32: generic machine,unreadable wand/controls,black bars instead of drainage','changes':['header-supported brew group,removable filter basket/handle and split spouts','wand joint and heat-resistant grip/recognisable tip','hollow sump with2mm bottom and17 metal grate bars with4mm real drainage gaps and rim','unbranded POWER/BREW/STEAM labels and panel fasteners'],'no_claim':'Functional visual assembly,not simulation of a real pressure/boiler system','photorealism_accepted':False,'requires':'same closeup judge placement,intersections,manufacture and realism'},indent=2));print('SAVED',out)
