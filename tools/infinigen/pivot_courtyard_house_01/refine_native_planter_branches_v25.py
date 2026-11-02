"""Use native skeleton centerlines with monotonic branch taper for the two porch planters."""
import bpy,json,math
from pathlib import Path
from mathutils import Vector,Matrix
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';rows=[]
for i in range(2):
 root=bpy.data.objects['PivotLeafyV9_planter_'+str(i)];members=list(root.children_recursive);body=next(o for o in members if o.type=='MESH' and any(m and 'bark' in m.name for m in o.data.materials));skeleton=next(o for o in members if o.type=='MESH' and len(o.data.vertices)<500 and len(o.data.edges)>0);bark=next(m for m in body.data.materials if m);transform=root.matrix_world.inverted()@skeleton.matrix_world;points=[transform@v.co for v in skeleton.data.vertices];lo=min(v.z for v in points);hi=max(v.z for v in points);scale=root.matrix_world.to_scale();assert max(scale)-min(scale)<1e-5,scale
 curve=bpy.data.curves.new('native_planter_tapered_branch_network','CURVE');curve.dimensions='3D';curve.bevel_depth=.010/scale.x;curve.bevel_resolution=3;curve.use_fill_caps=True
 for edge in skeleton.data.edges:
  sp=curve.splines.new('POLY');sp.points.add(1)
  for p,index in zip(sp.points,edge.vertices):
   co=points[index];p.co=(*co,1);p.radius=max(.16,1-.80*(co.z-lo)/(hi-lo))
 obj=bpy.data.objects.new('PivotEntryV25_native_tapered_branches_'+str(i),curve);bpy.context.scene.collection.objects.link(obj);obj.parent=root;obj.matrix_basis=Matrix.Identity(4);curve.materials.append(bark);obj['ir_room']='entry_deck';body.data=bpy.data.meshes.new('native_trunk_skin_replaced_by_tapered_tubes')
 rows.append({'planter':i,'native_skeleton':skeleton.name,'native_edges':len(skeleton.data.edges),'branch_base_radius_world_m':.010,'minimum_tip_radius_world_m':.0016,'root_local_z_range':[lo,hi],'canopy':'Original native leaf/twig hierarchy and transforms retained','old_body':'Mature bark skin removed; parent transform retained for native leaves'})
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v25';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v25.blend'));(B/'entry_branch_stage_v25.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','cause':'The v14 local trunk thinning left a mature-tree thickening above the thin base. V24 render review rejected that inverse-taper silhouette.','changes':rows,'remaining':['Verify original entry camera retains leaves and shows natural slender taper','Repeat physical audit and full 37-view regression']},indent=2)+'\n');print('PIVOT_ENTRY_BRANCHES_V25_SAVED',rows,flush=True)
