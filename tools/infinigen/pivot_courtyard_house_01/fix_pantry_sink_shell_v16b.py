"""Rebuild hollow cabinet/counter shell: overlapping inherited solid boxes capped Boolean sink recess."""
import bpy,bmesh,json,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
o=next(o for o in bpy.data.objects if o.name.startswith('PantryRunFactory') and o.get('ir_room')=='utility_0/1')
with bpy.data.libraries.load(str(F/'scene_rework_pantry_v13.blend'),link=False) as (src,dst):dst.objects=[n for n in src.objects if n==o.name]
original=next(x for x in dst.objects if x);o.data=original.data.copy();bpy.data.objects.remove(original,do_unlink=True)
bm=bmesh.new();bm.from_mesh(o.data);seen=set();remove=[];removed=[]
for start in list(bm.verts):
 if start in seen:continue
 stack=[start];seen.add(start);group=[]
 while stack:
  v=stack.pop();group.append(v)
  for edge in v.link_edges:
   other=edge.other_vert(v)
   if other not in seen:seen.add(other);stack.append(other)
 pts=[o.matrix_world@v.co for v in group];bounds=[[min(v[k] for v in pts),max(v[k] for v in pts)] for k in range(3)];x,y,z=bounds
 base=(x[1]-x[0]>2.7 and x[1]<19.7 and z[0]<.17 and 1.0<z[1]<1.10)
 top=(x[1]-x[0]>2.7 and x[1]<19.7 and 1.03<z[0]<1.10 and z[1]<1.12)
 fixture=(x[0]>17.05 and x[1]<17.85 and y[0]>10.60 and y[1]<11.34 and z[0]>1.04 and z[1]<1.70)
 if base or top or fixture:remove+=group;removed.append({'bounds':bounds,'base':base,'top':top,'fixture':fixture})
assert any(x['base'] for x in removed) and any(x['top'] for x in removed),removed
bmesh.ops.delete(bm,geom=remove,context='VERTS');bm.to_mesh(o.data);bm.free()
def box(c,s):return ('box',c,s,(0,0,0))
oak=bpy.data.materials['pivot_r16_residential_oak'];stone=bpy.data.materials['pivot_r14_limestone']
baseparts=[box((18.15,10.735,.59754),(2.9,.025,.90)),box((18.15,11.31,.59754),(2.9,.025,.90)),box((18.15,11.02,.16),(2.9,.60,.025))]+[box((x,11.02,.59754),(.025,.60,.90)) for x in [16.71,19.59]]
top=[box(((16.68954+17.17)/2,11.01454,1.06754),(17.17-16.68954,.62,.04)),box(((17.73+19.60954)/2,11.01454,1.06754),(19.60954-17.73,.62,.04)),box((17.45,(10.70454+10.84)/2,1.06754),(.56,10.84-10.70454,.04)),box((17.45,(11.24+11.32454)/2,1.06754),(.56,11.32454-11.24,.04))]
new=pa._prims('PivotPantryV16b_hollow_counter_shell',[(oak,baseparts),(stone,top)]);new['ir_room']='utility_0/1'
bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();hit,point,normal,face,obj,matrix=bpy.context.scene.ray_cast(dg,Vector((17.45,11.04,1.50)),Vector((0,0,-1)),distance=1.0)
audit={'hit':hit,'object':obj.name if obj else None,'point':list(point)};assert hit and obj.name.startswith('PivotPantryV16_recessed_sink') and point.z<.96,audit
bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_sink_v16b.blend'));(B/'pantry_sink_shell_v16b.json').write_text(json.dumps({'status':'recess_geometrically_verified_visual_review_pending','cause':'Boolean on overlapping closed cabinet and counter cubes created an upper closing cap, visible as a cutting-board-like lid','removed_components':removed,'fix':'Explicit hollow cabinet panels and four stone counter segments around sink','downward_ray_into_bowl':audit},indent=2)+'\n');print('PIVOT_SINK_SHELL_V16B_SAVED',audit,flush=True)
