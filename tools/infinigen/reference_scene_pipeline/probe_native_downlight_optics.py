import bpy,json
from pathlib import Path
root=Path(__file__).resolve().parents[3];r=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/native_downlight_pilot';bpy.ops.wm.open_mainfile(filepath=str(r/'source.blend'));o=bpy.data.objects['Native_Infinigen_downlight'];bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();ev=o.evaluated_get(dg);me=ev.to_mesh();rows=[]
for index,mat in enumerate(me.materials):
 fs=[f for f in me.polygons if f.material_index==index];down=[f for f in fs if f.normal.z<-.5];nodes=[]
 for n in mat.node_tree.nodes:
  if n.type in ['BSDF_TRANSPARENT','BSDF_TRANSLUCENT','MIX','EMISSION','LIGHT_PATH']:
   values={}
   for i,s in enumerate(n.inputs):
    if s.type in ['RGBA','VALUE'] and not s.is_linked:values[str(i)+':'+s.name]=list(s.default_value) if hasattr(s.default_value,'__len__') else s.default_value
   nodes.append({'name':n.name,'type':n.type,'values':values,'links':[(s.name,s.links[0].from_node.name) for s in n.inputs if s.is_linked]})
 rows.append({'slot':index,'material':mat.name,'faces':len(fs),'area_m2':sum(f.area for f in fs),'down_faces':len(down),'down_area_m2':sum(f.area for f in down),'down_projected_area_m2':sum(f.area*-f.normal.z for f in down),'nodes':nodes})
ev.to_mesh_clear();(r/'actual_optical_materials.json').write_text(json.dumps(rows,indent=2)+'\n');print('NATIVE_OPTICS_PROBE_COMPLETE',flush=True)
