"""Three library BottleFactory assets atreal bathroom scales;neutral isolated review,not room acceptance."""
import bpy,json,math,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
root=Path('/jarvis/project/robomituba');ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=ref/'native_toiletries_studio68';assert not out.exists();out.mkdir();bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
def material(name,color,rough):
 m=bpy.data.materials.new(name);m.use_nodes=True;p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*color,1);p.inputs['Roughness'].default_value=rough;p.inputs['IOR'].default_value=1.46;return m
cap=material('Toiletry68_molded_cap',(.06,.067,.07),.46);label=material('Toiletry68_brandless_paper_label',(.84,.82,.75),.58);rows=[]
for i,(seed,height,color) in enumerate([(1,.13,(.78,.76,.69)),(2,.16,(.20,.33,.28)),(4,.19,(.52,.35,.19))]):
 asset=root/f'data/object_library_v2/package/bottle_{seed:03}.blend'
 with bpy.data.libraries.load(str(asset),link=False) as (a,b):b.objects=list(a.objects)
 meshes=[o for o in b.objects if o and o.type=='MESH'];assert len(meshes)==1
 o=meshes[0];bpy.context.collection.objects.link(o);bpy.context.view_layer.update();pts=[o.matrix_world@Vector(v) for v in o.bound_box];lo=Vector([min(p[k] for p in pts) for k in range(3)]);hi=Vector([max(p[k] for p in pts) for k in range(3)]);factor=height/(hi.z-lo.z);anchor=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));o.matrix_world=Matrix.Translation(((i-1)*.17,0,0))@Matrix.Scale(factor,4)@Matrix.Translation(-anchor)@o.matrix_world;o.name=f'NativeToiletry68_bottle_{seed:03}';body=material(f'Toiletry68_body_{seed}',color,.32)
 # Retain native shape,material regions,cap andlabel geometry;remove source text/brands.
 assert len(o.data.materials)==3
 original=[m.name for m in o.data.materials]
 for slot,mat in enumerate([body,label,cap]):o.data.materials[slot]=mat
 for f in o.data.polygons:
  if f.material_index==0:f.use_smooth=True
 rows.append({'object':o.name,'source':str(asset),'source_sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),'seed':seed,'height_m':height,'uniform_scale':factor,'width_m':(hi.x-lo.x)*factor,'original_material_slots':original,'material_regions_preserved':True,'scope':'Native bottle,cap andlabel geometry retained;opaque plastic/brandless plain label/cap plastic trial.'})
bpy.ops.mesh.primitive_plane_add(size=10,location=(0,0,0));floor=bpy.context.object;floor.data.materials.append(material('studio_floor',(.34,.35,.36),.7));world=bpy.context.scene.world or bpy.data.worlds.new('StudioWorld');bpy.context.scene.world=world;world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Strength'].default_value=.25
for name,loc,power,size in [('key',(-.5,-.6,.7),35,.5),('fill',(.6,.1,.5),12,.35)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,.1))-o.location).to_track_quat('-Z','Y').to_euler()
views=[{'name':'native_toiletries_three','location':[.35,-.75,.38],'target':[0,0,.105],'hfov':43,'render_width':1280,'samples':32}];(out/'views.json').write_text(json.dumps(views,indent=2));(out/'scope.json').write_text(json.dumps({'sources':rows,'scope':'isolated native geometry/material preview,not room support/collision orphotographic acceptance'},indent=2));bpy.ops.wm.save_as_mainfile(filepath=str(out/'studio.blend'));print('Saved studio',out,flush=True)
