"""Functional pantry/garage detail pass; assess rendered readability, not item count."""
import bpy,math,json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
def mat(n,c,r=.6):
 m=bpy.data.materials.new(n);m.use_nodes=True;p=m.node_tree.nodes['Principled BSDF'];p.inputs['Base Color'].default_value=(*c,1);p.inputs['Roughness'].default_value=r;return m
oak=bpy.data.materials['layout_v2_oak'];stone=bpy.data.materials['pivot_r14_limestone'];dark=bpy.data.materials['layout_v2_dark_frame'];steel=bpy.data.materials['layout_v2_steel'];fibre=mat('storage_v5_woven_fibre',(.29,.18,.085));red=mat('storage_v5_toolcase_red',(.30,.055,.035));rubber=mat('storage_v5_hose_rubber',(.035,.065,.04));cream=bpy.data.materials['pantry_v2_ivory_ceramic']
def box(c,s):return ('box',c,s,(0,0,0))
def create(n,groups,room):
 o=pa._prims('PivotStorageV5_'+n,groups);o['ir_room']=room;return o
# Pantry full stone backsplash, with warm under-shelf task lights.
create('pantry_backsplash',[(stone,[box((19.3,9.165,1.32),(2.0,.025,.52))])],'utility_0/1')
for i,z in enumerate([1.575,2.075]):
 create('shelf_light_channel_'+str(i),[(dark,[box((19.3,9.355,z),(1.85,.022,.014))])],'utility_0/1')
 ld=bpy.data.lights.new('pantry_v5_warm_strip_'+str(i),'AREA');ld.energy=12;ld.color=(1,.75,.46);ld.shape='RECTANGLE';ld.size=1.80;ld.size_y=.035;lo=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(lo);lo.location=(19.3,9.355,z-.01)
# Bold woven bands and genuine grasp openings in front silhouette, no blank box fronts.
for i,x in enumerate([18.60,19.12]):
 create('pantry_basket_dark_handle_'+str(i),[(dark,[box((x,9.427,2.21504),(.13,.009,.038))]),(fibre,[box((x,9.433,2.24704),(.17,.012,.015)),box((x,9.433,2.18304),(.17,.012,.015))])],'utility_0/1')
# Domestic bowls on worktop, concentric interior profile (not opaque filled cylinders).
for i,z in enumerate([1.06104,1.09204]):
 bpy.ops.mesh.primitive_torus_add(major_radius=.084,minor_radius=.012,major_segments=48,minor_segments=12,location=(19.62,9.42,z+.025));o=bpy.context.object;o.name='PivotStorageV5_ceramic_bowl_rim_'+str(i);o.data.materials.append(cream);o['ir_room']='utility_0/1'
 create('bowl_base_'+str(i),[(cream,[('cyl',(19.62,9.42,z),(.055,.073,.012),(0,0,0))])],'utility_0/1')
# Garage upper shelf woven baskets and identifiable hard tool cases.
for i,y in enumerate([10.12,10.92]):
 z=1.9725;parts=[box((27.05,y,z+.012),(.44,.56,.024))]
 for k in range(10):
  yy=y-.25+k*.5/9;parts.append(box((27.28,yy,z+.13),(.018,.018,.25)))
 for k in range(8):parts.append(box((27.29,y,z+.025+k*.03),(.012,.56,.010)))
 for yy in [y-.28,y+.28]:parts.append(box((27.05,yy,z+.13),(.44,.02,.25)))
 create('garage_woven_basket_'+str(i),[(fibre,parts)],'garage_0/0')
for i,y in enumerate([12.1,12.84]):
 z=1.9725;create('garage_tool_case_'+str(i),[(red,[box((27.05,y,z+.13),(.40,.57,.26))]),(dark,[box((27.05,y,z+.267),(.14,.21,.035))]),(steel,[box((27.26,y-.19,z+.16),(.015,.035,.055)),box((27.26,y+.19,z+.16),(.015,.035,.055))])],'garage_0/0')
# Pegboard on south wall, backed and attached; hammer/screwdrivers/spanner distinct silhouettes.
create('garage_pegboard',[(oak,[box((28.80,9.18,1.68),(1.7,.045,1.1))])],'garage_0/0')
for i,x in enumerate([28.20,28.48,28.76,29.04,29.32]):
 length=.28 if i%2 else .36
 create('wall_tool_'+str(i),[(dark,[box((x,9.22,1.56),(.055,.045,.18))]),(steel,[box((x,9.22,1.56+length/2),(.018,.023,length))]+([box((x,9.22,1.56+length),(.22,.06,.07))] if i==0 else []))],'garage_0/0')
# A coiled hose with fitting, not a flat green disk.
for i,r in enumerate([.23,.25,.27,.29]):
 bpy.ops.mesh.primitive_torus_add(major_radius=r,minor_radius=.013,major_segments=64,minor_segments=12,location=(30.35,9.235+i*.023,1.40),rotation=(math.pi/2,0,0));o=bpy.context.object;o.name='PivotStorageV5_hose_coil_'+str(i);o.data.materials.append(rubber);o['ir_room']='garage_0/0'
create('hose_hook',[(steel,[box((30.35,9.22,1.70),(.08,.12,.045))])],'garage_0/0')
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='storage_v5_work_in_progress';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_storage_v5.blend'))
(B/'storage_stage_v5.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','changes':['Pantry stone backsplash and warm shelf strips','Stronger basket handles and bowls','Garage woven baskets and tool cases','Wall mounted tools and coiled hose'],'acceptance':'Pending original-camera render and support/clearance inspection'},indent=2)+'\n');print('PIVOT_STORAGE_V5_SAVED',flush=True)
