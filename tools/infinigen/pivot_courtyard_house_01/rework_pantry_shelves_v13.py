"""Replace closed north upper cabinets with supported, populated open oak shelving."""
import bpy,bmesh,json,sys
from pathlib import Path
from mathutils import Vector,Matrix
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
o=next(o for o in bpy.data.objects if o.name.startswith('PantryRunFactory') and o.get('ir_room')=='utility_0/1');bm=bmesh.new();bm.from_mesh(o.data);seen=set();remove=[];components=[]
for start in list(bm.verts):
 if start in seen:continue
 stack=[start];seen.add(start);group=[]
 while stack:
  v=stack.pop();group.append(v)
  for edge in v.link_edges:
   other=edge.other_vert(v)
   if other not in seen:seen.add(other);stack.append(other)
 low=min((o.matrix_world@v.co).z for v in group);slots={f.material_index for v in group for f in v.link_faces};names=[o.data.materials[i].name for i in slots if i<len(o.data.materials) and o.data.materials[i]]
 if low>1.50 and names and all(any(k in n for k in ['oak','pantry_cab','black_metal']) for n in names):remove+=group;components.append({'vertices':len(group),'minimum_z':low,'materials':names})
assert components,'No upper cabinet components identified; do not silently change the wrong geometry'
bmesh.ops.delete(bm,geom=remove,context='VERTS');bm.to_mesh(o.data);bm.free()
oak=bpy.data.materials['pivot_r16_residential_oak'];parts=[('box',(18.15,11.15,z),(2.7,.33,.035),(0,0,0)) for z in [1.59754,2.09754]]
new=pa._prims('PivotPantryV13_north_open_shelves',[(oak,parts)]);new['ir_room']='utility_0/1'
def copy_translate(source,name,delta):
 old=bpy.data.objects[source];new=old.copy();bpy.context.scene.collection.objects.link(new);new.name=name;new.matrix_world=Matrix.Translation(Vector(delta))@old.matrix_world;new['ir_room']='utility_0/1';return new
# Jar bottom and shelf top both 1.61504: exact supporting surface.
for i,x in enumerate([17.45,17.90,18.35,18.80]):
 j=i%3;oldx=[18.48,18.76,19.05][j]
 for suffix in ['', '_lid']:
  copy_translate('PivotPantryV2_food_jar_'+str(j)+suffix,'PivotPantryV13_jar_'+str(i)+suffix,(x-oldx,1.84,0))
 copy_translate('PivotPantryV2_contents_'+str(j),'PivotPantryV13_contents_'+str(i),(x-oldx,1.84,0))
for j,x in enumerate([18.75,19.15]):
 for k in range(5):copy_translate('PivotPantryV2_plate_%d_%d'%(j,k),'PivotPantryV13_upper_plate_%d_%d'%(j,k),(x-[19.43,19.88][j],1.84,.50))
# Existing household herbs, complete pot and leaf geometry, supported on upper shelf.
for suffix in ['herb_pot_0','herb_leaves_0']:
 copy_translate('PivotPantryV2_'+suffix,'PivotPantryV13_north_'+suffix,(17.15-19.85,11.15-9.30,0))
# Task light on the new working side.
ld=bpy.data.lights.new('pantry_v13_north_strip','AREA');ld.energy=14;ld.color=(1,.77,.49);ld.shape='RECTANGLE';ld.size=2.55;ld.size_y=.035;light=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(light);light.location=(18.15,11.10,1.565)
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_pantry_v13.blend'))
(B/'pantry_shelves_stage_v13.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','removed_upper_components':components,'changes':['Both pantry worktop sides now have open shelving','North shelves populated with four filled transparent jars, two plate stacks and herbs','Warm north task light','Refrigerator and sink/faucet retained'],'remaining':['Original camera plus opposite pantry view visual comparison','Jar/plate/herb support and appliance clearances','Whole scene reference validation']},indent=2)+'\n');print('PIVOT_PANTRY_V13_SAVED',flush=True)
