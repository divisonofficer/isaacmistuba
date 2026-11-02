"""Trace actual black image region against scene meshes and analytic area-light rectangles."""
import bpy,json,math,hashlib,numpy as np
from pathlib import Path
from PIL import Image
from scipy.ndimage import label,find_objects
from mathutils import Vector
root=Path(__file__).resolve().parents[3];ref=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';base=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';src=base/'scene_candidate_r84.blend';image=ref/'breakout_r84_private_product_chair/candidate/private_office_chair_front_detail.png';rgb=np.array(Image.open(image).convert('RGB'));height,width=rgb.shape[:2];mask=(rgb.max(axis=2)<4);labels,count=label(mask);regions=find_objects(labels);areas=np.bincount(labels.ravel());which=max(range(1,count+1),key=lambda i:areas[i]);ys,xs=np.where(labels==which);x=int(np.median(xs));y=int(np.median(ys));region=regions[which-1];bpy.ops.wm.open_mainfile(filepath=str(src));s=bpy.context.scene;s.render.resolution_x=width;s.render.resolution_y=height;s.render.resolution_percentage=100;data=bpy.data.cameras.new('Temporary_pixel_probe');camera=bpy.data.objects.new(data.name,data);s.collection.objects.link(camera);data.angle=math.radians(65);camera.location=(2.1,3.25,1.15);camera.rotation_euler=(Vector((2.5,4.25,.65))-camera.location).to_track_quat('-Z','Y').to_euler();bpy.context.view_layer.update();corners=data.view_frame(scene=s);vx=min(c.x for c in corners)+(x+.5)/width*(max(c.x for c in corners)-min(c.x for c in corners));vy=max(c.y for c in corners)-(y+.5)/height*(max(c.y for c in corners)-min(c.y for c in corners));direction=(camera.matrix_world.to_3x3()@Vector((vx,vy,corners[0].z))).normalized();origin=camera.location.copy();mesh_hits=[];cursor=origin.copy();travel=0.
for i in range(10):
 hit,point,normal,index,obj,matrix=s.ray_cast(bpy.context.evaluated_depsgraph_get(),cursor,direction,distance=100)
 if not hit:break
 distance=(point-origin).length;mesh_hits.append({'object':obj.name,'distance_m':distance,'point':list(point),'normal':list(normal),'hide_render':obj.hide_render,'visible_camera':getattr(obj,'visible_camera',None),'world_bounds':[[min((obj.matrix_world@Vector(c))[k] for c in obj.bound_box),max((obj.matrix_world@Vector(c))[k] for c in obj.bound_box)] for k in range(3)],'collections_render_hidden':all(c.hide_render for c in obj.users_collection),'material_slots':[m.name if m else None for m in obj.data.materials] if hasattr(obj.data,'materials') else []});cursor=point+direction*.0001
lights=[]
for obj in bpy.data.objects:
 if obj.type!='LIGHT' or obj.data.type!='AREA' or obj.hide_render:continue
 inverse=obj.matrix_world.inverted();o=inverse@origin;d=inverse.to_3x3()@direction
 if abs(d.z)<1e-9:continue
 t=-o.z/d.z
 if t<=0:continue
 local=o+d*t;hw=obj.data.size/2;hh=(obj.data.size_y if obj.data.shape in ['RECTANGLE','ELLIPSE'] else obj.data.size)/2
 inside=(local.x/hw)**2+(local.y/hh)**2<=1 if obj.data.shape in ['DISK','ELLIPSE'] else abs(local.x)<=hw and abs(local.y)<=hh
 if not inside:continue
 n=(obj.matrix_world.to_3x3().inverted().transposed()@Vector((0,0,-1))).normalized();lights.append({'object':obj.name,'parent':obj.parent.name if obj.parent else None,'distance_m':t,'viewed_from_back':n.dot(-direction)<0,'shape':obj.data.shape,'size_m':[obj.data.size,hh*2],'energy':obj.data.energy,'visible_camera':getattr(obj,'visible_camera',None)})
lights.sort(key=lambda x:x['distance_m']);d={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'frame':str(image),'frame_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'black_component_pixels':int(areas[which]),'pixel_xy':[x,y],'pixel_rgb':rgb[y,x].tolist(),'black_component_bbox_xy':[region[1].start,region[0].start,region[1].stop,region[0].stop],'ray_origin':list(origin),'ray_direction':list(direction),'mesh_hits':mesh_hits,'area_light_intersections':lights,'scope':'Geometric diagnosis foroneactual black-region ray,includingfinite area emitters excluded bymesh raycast. Does not prove causal removal until controlled render;no scene saved.'};(ref/'private_chair_r84_black_patch_visibility_probe.json').write_text(json.dumps(d,indent=2)+'\n');print(json.dumps(d,indent=2),flush=True)
