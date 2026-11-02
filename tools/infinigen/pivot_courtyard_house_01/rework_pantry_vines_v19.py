"""Native Infinigen leaf meshes on trailing pantry vines, practical LED diffusers, and bed repair."""
import bpy,json,math,random,sys,numpy as np
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
from infinigen.assets.objects.small_plants.leaf_general import LeafFactory
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';rng=random.Random(48712919);np.random.seed(48712919)
# Replace the complete soil component: a prior vertex threshold accidentally caught
# the west bed's 9.055m edge while expanding the far bed. Exact boxes avoid skew.
bpy.data.objects.remove(bpy.data.objects['PivotCourtyardV3_PlantingBeds'],do_unlink=True);soil=bpy.data.materials['courtyard_v3_soil']
o=pa._prims('PivotCourtyardV3_PlantingBeds',[(soil,[('box',(8.58,6.12,.13),(.95,3.85,.08),(0,0,0)),('box',(12.12,4.69,.13),(6.1,.98,.08),(0,0,0))])]);o['ir_room']='courtyard'
def material(n,c,r=.65):
 m=bpy.data.materials.new(n);m.use_nodes=True;p=m.node_tree.nodes['Principled BSDF'];p.inputs['Base Color'].default_value=(*c,1);p.inputs['Roughness'].default_value=r;return m
colors=[(.028,.12,.018),(.05,.18,.027),(.11,.22,.04)];leafm=[material('pantry_v19_native_leaf_'+str(i),c) for i,c in enumerate(colors)];prototypes=[]
for i in range(3):
 np.random.seed(48712919+i);o=LeafFactory(48712919+i,genome={'leaf_width':.55,'width_rand':.06,'use_wave':True}).create_asset();o.name='PivotNativeIvyLeafV19_'+str(i);bpy.context.view_layer.update();o.scale*=.075/max(o.dimensions);o.data.materials.append(leafm[i]);prototypes.append(o)
for name in ['PivotPantryV2_herb_pot_0','PivotPantryV2_herb_leaves_0','PivotPantryV13_north_herb_pot_0','PivotPantryV13_north_herb_leaves_0']:
 if name in bpy.data.objects:bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
potmat=bpy.data.materials['entry_v11_limestone'];leaf_count=0
for i,(x,y,front) in enumerate([(19.85,9.30,1),(17.15,11.15,-1)]):
 root=bpy.data.objects.new('PivotPantryV19_vine_'+str(i),None);bpy.context.scene.collection.objects.link(root);root['ir_room']='utility_0/1';bottom=2.11504;h=.18;profile=[(0,bottom),(.075,bottom),(.11,bottom+h),(.095,bottom+h),(.065,bottom+.012),(0,bottom+.012)];verts=[];faces=[];n=48
 for rad,z in profile:verts.extend((x+rad*math.cos(k*math.tau/n),y+rad*math.sin(k*math.tau/n),z) for k in range(n))
 for j in range(len(profile)-1):
  for k in range(n):faces.append((j*n+k,j*n+(k+1)%n,(j+1)*n+(k+1)%n,(j+1)*n+k))
 me=bpy.data.meshes.new('pantry_v19_open_vessel');me.from_pydata(verts,[],faces);me.materials.append(potmat);o=bpy.data.objects.new('PivotPantryV19_pot_'+str(i),me);bpy.context.scene.collection.objects.link(o);o.parent=root
 for p in me.polygons:p.use_smooth=True
 bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=.091,depth=.014,location=(x,y,bottom+h-.025));o=bpy.context.object;o.name='PivotPantryV19_soil_'+str(i);o.data.materials.append(soil);o.parent=root
 zsoil=bottom+h-.018
 for j in range(4):
  xoff=(j-1.5)*.055;length=rng.uniform(.36,.43);points=[(x+xoff*.4,y,zsoil),(x+xoff,y+front*.06,zsoil+.045)]+[(x+xoff+math.sin(t*5+j)*.035,y+front*(.07+.18*t),zsoil+.035-length*t) for t in np.linspace(0,1,12)]
  curve=bpy.data.curves.new('pantry_v19_vine_stem','CURVE');curve.dimensions='3D';curve.bevel_depth=.0017;curve.bevel_resolution=2;sp=curve.splines.new('POLY');sp.points.add(len(points)-1)
  for p,co in zip(sp.points,points):p.co=(*co,1)
  stem=bpy.data.objects.new('PivotPantryV19_stem_%d_%d'%(i,j),curve);bpy.context.scene.collection.objects.link(stem);curve.materials.append(leafm[0]);stem.parent=root
  for k,point in enumerate(points[2:]):
   for side in [-1,1]:
    src=prototypes[(j+k)%3];o=src.copy();bpy.context.scene.collection.objects.link(o);o.name='PivotPantryV19_native_leaf_%03d'%leaf_count;o.parent=root;o.location=point;o.rotation_euler=(-front*math.radians(rng.uniform(55,80)),rng.uniform(-.3,.3),side*.5+rng.uniform(-.3,.3));o.scale*=rng.uniform(.80,1.05);leaf_count+=1
for o in prototypes:bpy.data.objects.remove(o,do_unlink=True)
# Emissive diffuser strips are actual geometry, paired with the existing area lights.
em=material('pantry_v19_LED_diffuser',(1,.82,.58),.35);p=em.node_tree.nodes['Principled BSDF'];p.inputs['Emission Color'].default_value=(1,.65,.30,1);p.inputs['Emission Strength'].default_value=6
parts=[('box',(19.3,9.36,z),(1.85,.018,.008),(0,0,0)) for z in [1.565,2.065]]+[('box',(18.15,11.10,z),(2.55,.018,.008),(0,0,0)) for z in [1.576,2.076]]
o=pa._prims('PivotPantryV19_LED_diffusers',[(em,parts)]);o['ir_room']='utility_0/1'
for o in bpy.data.objects:
 if o.type=='LIGHT' and o.name.startswith(('pantry_v5_warm_strip','pantry_v13_north_strip')):o.data.energy=30;o.data.color=(1,.68,.35)
# Counter stone uses a dedicated toned-down material; bathrooms remain independent.
m=bpy.data.materials['pivot_r14_limestone'].copy();m.name='pantry_v19_grey_stone'
for n in m.node_tree.nodes:
 if n.type=='VALTORGB':n.color_ramp.elements[0].color=(.27,.25,.22,1);n.color_ramp.elements[1].color=(.38,.35,.31,1)
for o in bpy.data.objects:
 if o.type=='MESH' and o.get('ir_room')=='utility_0/1':
  for slot in o.material_slots:
   if slot.material and slot.material.name in ['pivot_r14_limestone','ir_counter_top_white_stone']:slot.material=m
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v19';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_pantry_v19.blend'));(B/'pantry_vines_stage_v19.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','engine_leaf_factory':'infinigen.assets.objects.small_plants.leaf_general.LeafFactory','native_leaf_count':leaf_count,'changes':['Two supported hollow pots with actual native-leaf trailing vines','Visible warm LED diffuser strips and task-light adjustment','Grey counter stone contrast','Rebuilt precise soil bed boxes to repair accidental west-bed edge skew'],'remaining':['Check vines against shelves/jars and ceiling','Same pantry cameras and courtyard regression','Explicit soil bounding and circulation audits']},indent=2)+'\n');print('PIVOT_PANTRY_V19_SAVED',leaf_count,flush=True)
