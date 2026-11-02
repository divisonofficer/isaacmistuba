"""Replace unsuccessful shrub prototypes with complete known-leafy native tree hierarchies."""
import bpy,json,random,math
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';rng=random.Random(48712990)
for o in list(bpy.data.objects):
 if o.name.startswith(('PivotBorderV6_WestShrub_','PivotBorderV6_FarShrub_','PivotBorderV6_LowShrub_','PivotEntryV6_PlanterShrub_')):bpy.data.objects.remove(o,do_unlink=True)
source=bpy.data.objects['PivotCourtyardTreeRig'];originals=[source,*source.children_recursive];assert len(originals)>1
# Use full hierarchy; the existing courtyard native tree has verified rendered foliage.
rows=[]
def clone(x,y,h,ground,role,i):
 mapping={}
 for old in originals:
  o=old.copy();bpy.context.scene.collection.objects.link(o);mapping[old]=o
 for old,o in mapping.items():
  o.parent=mapping.get(old.parent);o.matrix_parent_inverse=old.matrix_parent_inverse.copy();o.matrix_basis=old.matrix_basis.copy()
 root=mapping[source];root.name='PivotLeafyV9_'+role+'_'+str(i);root.scale*=h/3.3;root.location=(x,y,ground);root.rotation_euler.z=rng.uniform(0,math.tau);root['ir_room']='entry_deck' if role=='planter' else 'courtyard';root['ir_role']=role
 rows.append({'root':root.name,'target_height':h,'position':[x,y,ground],'hierarchy_objects':len(mapping)})
for i in range(10):clone(8.52+rng.uniform(-.08,.08),4.45+i*.36,rng.uniform(.83,1.05),.10,'west_shrub',i)
for i in range(15):clone(9.25+i*.42,4.37+rng.uniform(-.04,.04),rng.uniform(.65,.90),.10,'far_shrub',i)
for i in range(15):clone(9.3+i*.40,4.71,rng.uniform(.40,.53),.10,'low_shrub',i)
for i,(x,y,h) in enumerate([(24.85,14.25,1.2),(24.70,16.58,1.0)]):clone(x,y,h,.57555,'planter',i)
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='leafy_borders_v9_work_in_progress';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_leafy_v9.blend'))
(B/'leafy_stage_v9.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','source':'Complete PivotCourtyardTreeRig hierarchy, generated from actual Infinigen TreeFactory; verified original canopy retained','removed':'Rendered bare BushFactory prototypes, no visual acceptance','plants':rows,'remaining':['Original-camera foliage density and botanical scale review','Ground/root contact and path clearances','Reference-faithful facade, materials and full-scene regression']},indent=2)+'\n');print('PIVOT_LEAFY_V9_SAVED',len(rows),flush=True)
