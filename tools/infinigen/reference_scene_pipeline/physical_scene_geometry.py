"""Conservative physical candidates from actual render layer paths, not object-name roles.

Does not infer physical opacity from textures, or certify render-time displacement/instances.
"""
import bpy
from mathutils import Vector

def render_mesh_candidates(scene=None,view_layer=None):
 scene=scene or bpy.context.scene;view_layer=view_layer or bpy.context.view_layer;included_paths={};blocked_paths={}
 def walk(layer,path,blocked):
  path=path+[layer.name];reasons=blocked+(['view_layer_excluded'] if layer.exclude else [])+(['collection_hide_render'] if layer.collection.hide_render else [])
  for obj in layer.collection.objects:
   item={'collection_path':'/'.join(path),'reasons':reasons}
   (blocked_paths if reasons else included_paths).setdefault(obj.name,[]).append(item)
  for child in layer.children:walk(child,path,reasons)
 walk(view_layer.layer_collection,[],[]);objects=[];records=[]
 for obj in scene.objects:
  if obj.type!='MESH':continue
  reasons=[]
  if obj.hide_render:reasons.append('object_hide_render')
  if obj.name not in included_paths:reasons.append('no_enabled_render_collection_path')
  selected=not reasons
  if selected:objects.append(obj)
  records.append({'object':obj.name,'included':selected,'reasons':reasons,'enabled_collection_paths':included_paths.get(obj.name,[]),'blocked_collection_paths':blocked_paths.get(obj.name,[]),'camera_ray_visible':obj.visible_camera,'viewport_visible':obj.visible_get(),'program_key':str(obj.get('program_key',''))})
 return objects,records

def evaluated_surface(obj,depsgraph=None):
 """World triangles and faced vertices only; loose native joint points are not surfaces."""
 depsgraph=depsgraph or bpy.context.evaluated_depsgraph_get();eo=obj.evaluated_get(depsgraph);mesh=eo.to_mesh()
 try:
  mesh.calc_loop_triangles();triangles=[tuple(t.vertices) for t in mesh.loop_triangles];used={i for f in triangles for i in f};points=[eo.matrix_world@v.co for v in mesh.vertices];return points,triangles,used
 finally:eo.to_mesh_clear()
