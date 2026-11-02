"""Measured fridge bay: support contact, non-overlapping adjacent door and intentional ventilation trim."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from material_detail import material
from detail_primitives import box,rod
ROOT=Path(__file__).resolve().parents[3]
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r35.blend';out=base/'scene_candidate_r36.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));fridge=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_fridge');shelf=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_bottom_panel');worktop=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_worktop');bpy.context.view_layer.update();support=max((shelf.matrix_world@Vector(c)).z for c in shelf.bound_box);h=fridge.dimensions.z;oldbottom=min((fridge.matrix_world@Vector(c)).z for c in fridge.bound_box);fridge.location.z+=support-oldbottom;bpy.context.view_layer.update();pts=[fridge.matrix_world@Vector(c) for c in fridge.bound_box];xfront=min(p.x for p in pts);left=min(p.y for p in pts);right=max(p.y for p in pts);bottom=min(p.z for p in pts);top=max(p.z for p in pts);counter_under=min((worktop.matrix_world@Vector(c)).z for c in worktop.bound_box);airgap=counter_under-top;assert .01<airgap<.03,airgap
# The next original door overlapped the fridge by120mm. Keep its far edge and reduce its width to clear the measured bay.
front=min((o for o in bpy.data.objects if o.get('program_key')=='coffee_cabinet_front'),key=lambda o:o.location.y);oldpoints=[front.matrix_world@Vector(c) for c in front.bound_box];oldlo=min(p.y for p in oldpoints);hi=max(p.y for p in oldpoints);newlo=right+.012;front.location.y=(newlo+hi)/2;front.dimensions.y=hi-newlo;assert front.dimensions.y>.3
metal=fridge.data.materials[0];rubber=material('FridgeR36_door_gasket',(.009,.010,.011),.72)[0];oak=front.data.materials[0]
# Closed appliance door and its actual gasket; original chassis remains behind it.
box('fridge_door_panel',(xfront-.006,fridge.location.y,fridge.location.z),(.008,fridge.dimensions.y-.010,h-.016),metal,.003)
for y in [left+.008,right-.008]:box('fridge_gasket_side',(xfront-.001,y,fridge.location.z),(.002,.004,h-.020),rubber,.0005)
for z in [bottom+.008,top-.008]:box('fridge_gasket_horizontal',(xfront-.001,fridge.location.y,z),(.002,fridge.dimensions.y-.012,.004),rubber,.0005)
# A visible15mm ventilation grille explains the intentional service gap above the unit.
for z in [top+.001,counter_under-.001]:box('fridge_vent_grille_frame',(xfront+.002,fridge.location.y,z),(.012,fridge.dimensions.y,.002),metal,.0004)
for i in range(17):box('fridge_vent_grille_slat',(xfront+.002,left+.012+i*(fridge.dimensions.y-.024)/16,(top+counter_under)/2),(.009,.0018,airgap-.004),metal,.0003)
# Full-depth veneer filler stops the side gap without filling the ventilation channel.
box('fridge_left_bay_filler',(13.9475,(3.43+left)/2,(support+counter_under)/2),(.035,left-3.43,counter_under-support),oak,.001)
for o in list(bpy.data.objects):
 if o.get('program_key')=='fridge_door_handle':bpy.data.objects.remove(o,do_unlink=True)
z=top-.065;yc=fridge.location.y
for side in [-1,1]:rod('fridge_handle_standoff',(xfront-.010,yc+side*.085,z),(xfront-.038,yc+side*.085,z),.0045,metal)
rod('fridge_door_handle',(xfront-.038,yc-.10,z),(xfront-.038,yc+.10,z),.006,metal)
bpy.context.view_layer.update();newpts=[front.matrix_world@Vector(c) for c in front.bound_box];assert min(p.y for p in newpts)>right+.011;assert abs(min((fridge.matrix_world@Vector(c)).z for c in fridge.bound_box)-support)<1e-6;bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r36.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'trigger':'Independent review: refrigerator/counter black joint gap; measured actual support and neighbour panel','measurements':{'old_fridge_support_penetration_m':support-oldbottom,'new_support_gap_m':0,'old_adjacent_door_overlap_m':right-oldlo,'new_adjacent_door_clearance_m':.012,'intentional_top_ventilation_gap_m':airgap},'changes':['fridge sits on actual shelf','adjacent door no longer intersects fridge chassis','separate closed door/gasket/open handle','vent grille and veneer filler distinguish service clearance from missing geometry'],'photorealism_accepted':False,'requires':'wide and chair-detail installation review; no full-scene acceptance'},indent=2));print('SAVED',out)
