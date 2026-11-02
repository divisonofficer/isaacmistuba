"""Physical downlights and vanity reflection sources for clean wet rooms."""
import bpy
from mathutils import Vector

def apply(mapping):
    added=[];lens=bpy.data.materials.new('Realism_downlight_diffuser');lens.use_nodes=True;bs=lens.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.85,.85,.83,1);bs.inputs['Emission Color'].default_value=(1,.93,.84,1);bs.inputs['Emission Strength'].default_value=2
    for key,row in mapping.items():
        if not row['room_id'].startswith('bathroom'):continue
        floor=bpy.data.objects[row['room_id']+'.floor'];ceiling=bpy.data.objects[row['room_id']+'.ceiling'];pts=[floor.matrix_world@Vector(c) for c in floor.bound_box];x0,x1=min(p.x for p in pts),max(p.x for p in pts);y0,y1=min(p.y for p in pts),max(p.y for p in pts);cz=min((ceiling.matrix_world@Vector(c)).z for c in ceiling.bound_box)
        ambient=bpy.data.objects.get('res03_area_'+key);power=ambient.data.energy if ambient else 70
        if ambient:ambient.data.energy=power*.55
        for i,(u,v) in enumerate([(.30,.30),(.75,.70)]):
            x,y=x0+(x1-x0)*u,y0+(y1-y0)*v
            data=bpy.data.lights.new(f'Realism_{key}_downlight_{i}','AREA');data.energy=power*.2;data.shape='DISK';data.size=.14;data.color=(1,.95,.88)
            light=bpy.data.objects.new(data.name,data);bpy.context.scene.collection.objects.link(light);light.location=(x,y,cz-.045)
            bpy.ops.mesh.primitive_cylinder_add(vertices=24,radius=.078,depth=.016,location=(x,y,cz-.016));trim=bpy.context.object;trim.name=f'Realism_{key}_downlight_trim_{i}';trim.data.materials.append(lens);trim['reference_scene_owner']='dual_unit_residential_floor_03';trim['program_key']=key+'_downlight';trim['audit_kind']='ceiling_fixture';trim['reference_ceiling_detail']=True
            added.append(light.name)
        vanity=next((o for o in bpy.data.objects if o.get('program_key')==key+'_vanity'),None)
        if vanity:
            position=vanity.matrix_world@Vector((.075,0,1.55));direction=(vanity.matrix_world.to_3x3()@Vector((1,0,0))).normalized();data=bpy.data.lights.new(f'Realism_{key}_mirror_bar','AREA');data.energy=5;data.shape='RECTANGLE';data.size=.65;data.size_y=.045;data.color=(1,.94,.85);obj=bpy.data.objects.new(data.name,data);bpy.context.scene.collection.objects.link(obj);obj.location=position;obj.rotation_euler=direction.to_track_quat('-Z','Y').to_euler();added.append(obj.name)
    return added
