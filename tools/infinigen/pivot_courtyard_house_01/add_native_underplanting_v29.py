"""Add distinct broad-leaf understory using previously generated engine leaf meshes."""
import bpy, math, random, json
from pathlib import Path
from mathutils import Vector

R=Path(__file__).resolve().parents[3]
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
rng=random.Random(48712929)
source=next(o for o in bpy.data.objects if o.name.startswith('PivotPantryV19_native_leaf_') and o.type=='MESH')
palettes=[(.16,.25,.075),(.25,.32,.15),(.085,.19,.07)]
meshes=[]
for i,c in enumerate(palettes):
    mesh=source.data.copy();mesh.materials.clear()
    m=bpy.data.materials.new('understory_v29_native_leaf_%d'%i);m.use_nodes=True
    p=m.node_tree.nodes['Principled BSDF'];p.inputs['Base Color'].default_value=(*c,1);p.inputs['Roughness'].default_value=.58
    p.inputs['Subsurface Weight'].default_value=.06
    mesh.materials.append(m);meshes.append(mesh)
stemmat=bpy.data.materials['pantry_v2_leaf']
leaf_count=0;rows=[]
def shrub(x,y,z,h,spread,label,index):
    global leaf_count
    root=bpy.data.objects.new('PivotUnderstoryV29_%s_%02d'%(label,index),None)
    bpy.context.scene.collection.objects.link(root)
    root['ir_room']='courtyard' if label=='border' else 'entry_deck'
    root['engine_leaf_source']='Infinigen LeafFactory / pantry_v19 native mesh'
    for branch in range(7):
        angle=branch*math.tau/7+rng.uniform(-.15,.15)
        reach=spread*rng.uniform(.65,1)
        height=h*rng.uniform(.65,1)
        pts=[Vector((x+math.cos(angle)*reach*t*t,y+math.sin(angle)*reach*t*t,z+height*t)) for t in (0,.2,.4,.6,.8,1)]
        curve=bpy.data.curves.new('understory_v29_connected_stem','CURVE');curve.dimensions='3D';curve.bevel_depth=.0022;curve.bevel_resolution=2
        sp=curve.splines.new('BEZIER');sp.bezier_points.add(len(pts)-1)
        for p,co in zip(sp.bezier_points,pts):p.co=co;p.handle_left_type='AUTO';p.handle_right_type='AUTO'
        stem=bpy.data.objects.new(root.name+'_stem_%d'%branch,curve);bpy.context.scene.collection.objects.link(stem);stem.parent=root;curve.materials.append(stemmat)
        for node,co in enumerate(pts[2:]):
            for side in (-1,1):
                leaf=bpy.data.objects.new('PivotUnderstoryV29_native_leaf_%04d'%leaf_count,meshes[(index+branch)%3]);bpy.context.scene.collection.objects.link(leaf);leaf.parent=root
                leaf.location=co
                leaf.rotation_euler=(rng.uniform(.25,.75),side*.35,angle+side*.8)
                leaf.scale=source.scale.copy()
                bpy.context.view_layer.update()
                leaf.scale*=rng.uniform(.075,.105)/max(leaf.dimensions)
                leaf_count+=1
    rows.append({'root':root.name,'soil_root':[x,y,z],'height_m':h,'max_stem_spread_m':spread,'role':label})
for i in range(12):shrub(9.25+i*.49,4.96,.17,rng.uniform(.26,.43),.15,'border',i)
for i,(x,y) in enumerate([(24.85,14.25),(24.70,16.58)]):shrub(x,y,.57555,.72,.13,'planter',i)
bpy.context.view_layer.update()
bpy.context.scene['pivot_revision']='quality_rework_v29_understory_candidate'
bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v29.blend'))
(B/'native_underplanting_v29.json').write_text(json.dumps({'status':'saved_original_view_visual_review_pending','source_scene':'scene_rework_integrated_v28.blend','native_leaf_source':source.name,'native_leaf_instances':leaf_count,'plants':rows,'remaining':['Original courtyard/entry views and planter botanical scale','Actual geometry route and soil checks','No acceptance from instance counts alone']},ensure_ascii=False,indent=2)+'\n')
print('PIVOT_UNDERSTORY_V29_SAVED',leaf_count,flush=True)
