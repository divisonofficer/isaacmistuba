"""Native mature trees, guest privacy, and a comparable kitchen viewpoint."""
import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
base=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';fixes=[]
p=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full/landscape_tree.blend';assert p.exists()
with bpy.data.libraries.load(str(p),link=False) as (src,dst):dst.objects=list(src.objects)
root=next(o for o in dst.objects if o and o.get('pivot_native_landscape_tree'))
family=[root,*root.children_recursive]
for o in family:
 if o.name not in bpy.context.scene.objects:bpy.context.scene.collection.objects.link(o)
rig=bpy.data.objects.new('PivotMatureTreeRig',None);bpy.context.scene.collection.objects.link(rig);root.parent=rig
bpy.context.view_layer.update()
pts=[o.matrix_world@Vector(v) for o in family if o.type=='MESH' and not o.hide_render for v in o.bound_box]
assert pts
height=max(v.z for v in pts)-min(v.z for v in pts);assert .5<height<100,height
center=Vector(((max(v.x for v in pts)+min(v.x for v in pts))/2,(max(v.y for v in pts)+min(v.y for v in pts))/2,min(v.z for v in pts)))
scale=5.8/height;rig.scale=(scale,)*3;rig.location=Vector((3,27,.1))-center*scale
for i,(x,y,h) in enumerate([(8,27,6.2),(13,27,5.9),(18,27,6.5),(24,28,5.8),(3,34,7.5),(12,35,7.0),(22,35,7.4)]):
 mapping={}
 for orig in [rig,*family]:
  c=orig.copy();bpy.context.scene.collection.objects.link(c);mapping[orig]=c
 for orig,c in mapping.items():
  c.parent=mapping.get(orig.parent);c.matrix_parent_inverse=orig.matrix_parent_inverse.copy();c.matrix_basis=orig.matrix_basis.copy()
 new=mapping[rig];factor=h/height;new.scale=(factor,)*3;new.location=Vector((x,y,.1))-center*factor
fixes.append({'issue':'sparse small foliage unlike mature reference garden','action':'native Infinigen TreeFactory summer tree; 9 real geometry instances at 5.8–7.5 m, outside house footprint','prototype_height_m':height})
# Add plausible turf variation rather than a bright uniform plane.
m=bpy.data.materials['pivot_r8_lawn'];nt=m.node_tree;bs=nt.nodes.get('Principled BSDF');noise=nt.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=18;ramp=nt.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(.018,.05,.008,1);ramp.color_ramp.elements[1].color=(.065,.13,.025,1);nt.links.new(noise.outputs['Fac'],ramp.inputs['Fac']);nt.links.new(ramp.outputs['Color'],bs.inputs['Base Color'])
# The guest bath opening is defined by the source at x=18,y=2.4..3.3.
# Record a closed door state; the floorplan opening remains unchanged.
wood=pa._flat('pivot_r9_guest_door',(.65,.60,.51),.75);metal=pa._flat('pivot_r9_door_handle',(.12,.13,.14),.3,1)
door=pa._prims('PivotGuestPrivacyDoorFactory(1201).spawn_asset(1201)',[(wood,[('box',(18,2.85,1.20),(.045,.84,2.10),(0,0,0))]),(metal,[('cyl',(17.955,2.55,1.10),(.018,.018,.10),(0,math.pi/2,0)),('box',(17.925,2.62,1.10),(.025,.16,.025),(0,0,0))])]);door['pivot_door_state']='closed';door['pivot_source_opening']='guest_bath'
fixes.append({'issue':'toilet visible from guest meal table','action':'closed guest bath door in existing source opening; no floorplan change','navigation_note':'door state must be respected by any later traversability export'})
views=json.loads((ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full/review_views_r7.json').read_text());views.append({'name':'kitchen_reference_wide','location':[13.4,13.05,1.7],'target':[13.4,9.7,1.15],'hfov':82})
(ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full/review_views_r9.json').write_text(json.dumps(views,indent=2))
bpy.context.view_layer.update();invalid=[o.name for o in bpy.data.objects if o.type=='MESH' and any(not math.isfinite(v) or abs(v)>100 for v in o.dimensions)];assert not invalid,invalid
bpy.context.scene['pivot_revision']='r9_direct_review';bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full/scene_review_r9.blend'))
(base/'revision_r9.json').write_text(json.dumps({'fixes':fixes,'invalid_mesh_extents':invalid,'limitations':['Mature trees procedural, not surveyed species or exact garden layout','Transparent glazing is a review approximation','Closed guest door requires navigation-state handling before dataset export']},indent=2));print('PIVOT_R9_COMPLETE',flush=True)
