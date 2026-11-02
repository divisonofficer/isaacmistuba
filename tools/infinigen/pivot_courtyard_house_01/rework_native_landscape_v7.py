"""Replace sparse stems with genuine Infinigen shrubs/grass and hollow entry vessels."""
import bpy,json,math,random
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';rng=random.Random(48712666)
for o in list(bpy.data.objects):
 if o.name.startswith('PivotCourtyardV3_Plant_') or o.name.startswith('PivotEntryV4_planter_'):bpy.data.objects.remove(o,do_unlink=True)
with bpy.data.libraries.load(str(F/'native_borders_v7.blend'),link=False) as (src,dst):dst.objects=[n for n in src.objects if n.startswith(('PivotNativeBushV6_','PivotNativeGrassV6'))]
prototypes={o.name:o for o in dst.objects if o};bushes=[prototypes['PivotNativeBushV6_'+str(i)] for i in range(3)];grass=prototypes['PivotNativeGrassV6'];rows=[]
def place(src,name,x,y,height,ground,role):
 o=src.copy();o.data=src.data;bpy.context.scene.collection.objects.link(o);o.name=name;o.parent=None;o.location=(0,0,0);o.rotation_euler=(0,0,rng.random()*math.tau);o.scale=(1,1,1);bpy.context.view_layer.update();pts=[o.matrix_world@Vector(v) for v in o.bound_box];h=max(v.z for v in pts)-min(v.z for v in pts);o.scale*=height/max(h,.01);o.location.x=x;o.location.y=y;bpy.context.view_layer.update();pts=[o.matrix_world@Vector(v) for v in o.bound_box];o.location.z=ground-min(v.z for v in pts);o['ir_room']='entry_deck' if role=='planter' else 'courtyard';o['ir_role']=role;rows.append({'name':name,'prototype':src.name,'height':height,'ground':ground});return o
for i in range(9):place(bushes[i%3],'PivotBorderV6_WestShrub_%02d'%i,8.53+rng.uniform(-.08,.08),4.52+i*.39,rng.uniform(.65,.94),.17,'shrub')
for i in range(14):place(bushes[(i+1)%3],'PivotBorderV6_FarShrub_%02d'%i,9.25+i*.44,4.40+rng.uniform(-.04,.04),rng.uniform(.48,.76),.17,'shrub')
for i in range(20):place(grass,'PivotBorderV6_WestGrass_%02d'%i,8.93+rng.uniform(-.04,.02),4.38+i*.18,rng.uniform(.22,.35),.17,'low_grass')
for i in range(30):place(grass,'PivotBorderV6_FarGrass_%02d'%i,9.2+i*.20,4.74+rng.uniform(-.04,.02),rng.uniform(.19,.29),.17,'low_grass')
# Add smaller shrubs between larger groups to fill near-soil gaps with real leaves.
for i in range(15):place(bushes[i%3],'PivotBorderV6_LowShrub_%02d'%i,9.27+i*.4,4.69,rng.uniform(.28,.40),.17,'low_shrub')
rig=bpy.data.objects.get('PivotCourtyardTreeRig')
if rig:rig.location.x=11.0;rig.location.y=5.0
# Lathed double-wall planters: open top, interior soil, tapered stoneware sides.
stone=bpy.data.materials['pivot_r14_limestone'];soil=bpy.data.materials['courtyard_v3_soil']
for i,(x,y,h) in enumerate([(24.85,14.25,1.15),(24.70,16.58,.9)]):
 bottom=.14555;profile=[(0,bottom),(.165,bottom),(.23,bottom+.45),(.23,bottom+.48),(.20,bottom+.48),(.195,bottom+.41),(.15,bottom+.04),(0,bottom+.04)];verts=[];faces=[];n=64
 for rad,z in profile:verts.extend((x+rad*math.cos(k*math.tau/n),y+rad*math.sin(k*math.tau/n),z) for k in range(n))
 for j in range(len(profile)-1):
  for k in range(n):faces.append((j*n+k,j*n+(k+1)%n,(j+1)*n+(k+1)%n,(j+1)*n+k))
 me=bpy.data.meshes.new('entry_v6_hollow_vessel');me.from_pydata(verts,[],faces);me.materials.append(stone);o=bpy.data.objects.new('PivotEntryV6_HollowPlanter_'+str(i),me);bpy.context.scene.collection.objects.link(o);o['ir_room']='entry_deck'
 for p in me.polygons:p.use_smooth=True
 bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=.193,depth=.015,location=(x,y,bottom+.42));o=bpy.context.object;o.name='PivotEntryV6_PlanterSoil_'+str(i);o.data.materials.append(soil)
 place(bushes[i],'PivotEntryV6_PlanterShrub_'+str(i),x,y,h,bottom+.43,'planter')
for o in prototypes.values():
 if not o.users_collection:bpy.data.objects.remove(o,do_unlink=True)
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='native_landscape_v7_work_in_progress';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_native_v7.blend'))
(B/'native_landscape_stage_v7.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','native_engine_factories':['BushFactory','GrassTuftFactory'],'source':'native_borders_v7.blend','placements':rows,'plant_count':len(rows),'acceptance':'Requires same-camera review and clearance audit'},indent=2)+'\n');print('PIVOT_NATIVE_V7_SAVED',len(rows),flush=True)
