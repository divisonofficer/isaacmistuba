"""Inspect actual saved window shaders and render bounce settings; no scene edits."""
import bpy,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[3];base=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';src=base/'scene_candidate_r83.blend';bpy.ops.wm.open_mainfile(filepath=str(src));objects=[];materials={}
for o in bpy.data.objects:
 if o.type!='MESH' or 'WindowFactory' not in o.name:continue
 objects.append({'name':o.name,'vertices':len(o.data.vertices),'dimensions':list(o.dimensions),'materials':[m.name if m else None for m in o.data.materials]})
 for m in o.data.materials:
  if not m or m.name in materials:continue
  nodes=[]
  if m.use_nodes:
   for n in m.node_tree.nodes:
    if n.type not in ['BSDF_PRINCIPLED','BSDF_GLASS','BSDF_GLOSSY','BSDF_TRANSPARENT','OUTPUT_MATERIAL','VOLUME_ABSORPTION']:continue
    row={'name':n.name,'type':n.type,'inputs':{}}
    for socket in n.inputs:
     if socket.name not in ['Base Color','Color','Roughness','Metallic','IOR','Transmission Weight','Coat Weight','Coat Roughness','Density','Normal','Surface','Volume']:continue
     val=getattr(socket,'default_value',None)
     if val is not None and not isinstance(val,(str,int,float,bool)):
      try:val=list(val)
      except TypeError:val=str(val)
     row['inputs'][socket.name]={'value':val,'linked_from':[{'node':l.from_node.name,'type':l.from_node.type,'socket':l.from_socket.name} for l in socket.links]}
    nodes.append(row)
  materials[m.name]=nodes
s=bpy.context.scene;c=s.cycles;d={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'window_objects':objects,'materials':materials,'cycles':{k:getattr(c,k) for k in ['max_bounces','diffuse_bounces','glossy_bounces','transmission_bounces','transparent_max_bounces']},'scope':'Saved window mesh/material/bounce inventory only;does not establish Fresnel correctness,duplicate panes,physical thickness,ray obstruction orimage realism.'};p=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/window_material_probe_r83.json';p.write_text(json.dumps(d,indent=2)+'\n');print('Recorded actual window objects',len(objects),'materials',len(materials),flush=True)
