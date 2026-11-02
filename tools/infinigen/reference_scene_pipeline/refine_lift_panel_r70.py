"""Manufacture-only elevator call-panel trial; no layout/light changes or acceptance."""
import bpy, json, hashlib, math
from pathlib import Path
from mathutils import Vector
root=Path('/jarvis/project/robomituba');base=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r69.blend';out=base/'scene_candidate_r70.blend'
assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));body=bpy.data.objects['Residential03_lift_call_panel'];bpy.context.view_layer.update();points=[body.matrix_world@Vector(v) for v in body.bound_box];lo=Vector([min(v[k] for v in points) for k in range(3)]);hi=Vector([max(v[k] for v in points) for k in range(3)]);center=(lo+hi)/2
assert abs((hi-lo).x-.04)<1e-5 and abs((hi-lo).y-.12)<1e-5
# The existing mount footprint and rear support plane are preserved; reduce bulky projection.
old_world=[body.matrix_world@v.co for v in body.data.vertices]
for v,w in zip(body.data.vertices,old_world):
 w.x=lo.x+(w.x-lo.x)*.3;v.co=body.matrix_world.inverted()@w
body.data.update();backfront=lo.x+.012;parts=[]
def material(name,color,rough,metal=0):
 m=bpy.data.materials.new(name);m.use_nodes=True;b=m.node_tree.nodes.get('Principled BSDF');b.inputs['Base Color'].default_value=(*color,1);b.inputs['Roughness'].default_value=rough;b.inputs['Metallic'].default_value=metal;return m
steel=material('Lift70_satin_stainless',(.48,.51,.53),.29,1);b=steel.node_tree.nodes.get('Principled BSDF');anis=b.inputs.get('Anisotropic IOR Level') or b.inputs.get('Anisotropic');assert anis is not None;anis.default_value=.35
nt=steel.node_tree;tc=nt.nodes.new('ShaderNodeTexCoord');noise=nt.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=700;nt.links.new(tc.outputs['Object'],noise.inputs['Vector']);rm=nt.nodes.new('ShaderNodeMapRange');rm.inputs['To Min'].default_value=.265;rm.inputs['To Max'].default_value=.315;nt.links.new(noise.outputs['Fac'],rm.inputs['Value']);nt.links.new(rm.outputs[0],b.inputs['Roughness'])
dark=material('Lift70_recess_gasket',(.013,.016,.019),.55);buttonmat=material('Lift70_button_face',(.31,.34,.36),.22,1);symbol=material('Lift70_engraved_symbol',(.022,.027,.031),.45)
def register(o,name,mat,bevel=0):
 o.name='Lift70_'+name;o.data.materials.append(mat);o['program_key']='lift_call_panel__detail__'+name;o['audit_kind']='detail';o['reference_scene_owner']='dual_unit_residential_floor_03'
 if bevel:
  mod=o.modifiers.new('Manufactured edge radius','BEVEL');mod.width=bevel;mod.segments=3
 parts.append(o);return o
def box(name,loc,size,mat,bevel):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.dimensions=size;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);return register(o,name,mat,bevel)
def disk(name,x,y,z,r,depth,mat):
 bpy.ops.mesh.primitive_cylinder_add(vertices=64,radius=r,depth=depth,location=(x,y,z),rotation=(0,math.pi/2,0));o=register(bpy.context.object,name,mat,.00035)
 for f in o.data.polygons:f.use_smooth=len(f.vertices)==4
 return o
# Gasket covers the retained support; faceplate rests on it, with a visible 1mm border.
box('gasket',(backfront+.0006,center.y,center.z),(.0012,.118,.268),dark,.001)
plate=box('faceplate',(backfront+.00195,center.y,center.z),(.0015,.114,.264),steel,.001)
front=backfront+.0027
for label,z,up in [('up',center.z+.046,True),('down',center.z-.046,False)]:
 disk(label+'_button_recess',front+.00035,center.y,z,.019,.0007,dark)
 disk(label+'_button_bezel',front+.00105,center.y,z,.0175,.0014,steel)
 disk(label+'_button_cap',front+.0019,center.y,z,.0145,.0011,buttonmat)
 # A shallow inset-style dark triangular legend; no unmotivated emissive light.
 x=front+.00248; h=.005;w=.005
 yz=[(center.y-w,z-h if up else z+h),(center.y+w,z-h if up else z+h),(center.y,z+h if up else z-h)]
 me=bpy.data.meshes.new('arrow');me.from_pydata([(x,y,q) for y,q in yz],[],[(0,1,2)]);me.update();o=bpy.data.objects.new('arrow',me);bpy.context.collection.objects.link(o);register(o,label+'_direction',symbol)
# Small captive fastener heads above/below controls, each with a narrow slot.
for i,z in enumerate([center.z-.111,center.z+.111]):
 disk('fastener_'+str(i),front+.00025,center.y,z,.0023,.0005,steel)
 box('fastener_slot_'+str(i),(front+.00052,center.y,z),(.00004,.0027,.00045),dark,0)
body['manufacture_trial']='r70 retained support, shallow faceplate, paired physical call buttons'
views=json.loads((base/'review_views_fine_r45.json').read_text());views.append({'name':'lift_call_panel_manufacture_detail','location':[center.x+.55,center.y+.23,center.z+.11],'target':[front,center.y,center.z],'hfov':45,'render_width':1280,'samples':48,'scope':'Additional panel manufacture diagnostic, not replacement for required39'})
(ref/'review_views_lift_r70.json').write_text(json.dumps(views,indent=2));bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r70.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'candidate_sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'changes':'Only existing call-panel support depth and added faceplate/gasket/buttons/legends/fasteners. No camera, light, exposure, door or circulation changes.','retained_rear_x_m':lo.x,'support_depth_before_m':.04,'support_depth_after_m':.012,'button_diameter_m':.029,'parts':[o.name for o in parts],'photorealism_accepted':False,'requires':'saved-source five audits and same-camera wide/detail direct and independent comparison'},indent=2));print('Saved candidate70 panel trial',len(parts),flush=True)
