"""Projected front silhouette,not a Z=0 cross-section: avoids false notch from warped seam planes."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';rows=[]
for filename in ['native_pillow_prototypes.blend','native_pillow_panel_rest_prototypes.blend','native_pillow_panel_rest90_prototypes.blend']:
 path=ref/filename;bpy.ops.wm.open_mainfile(filepath=str(path));bpy.context.view_layer.update()
 for o in bpy.data.objects:
  if o.type!='MESH':continue
  ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh();lo=[min(v.co[k] for v in mesh.vertices) for k in range(3)];hi=[max(v.co[k] for v in mesh.vertices) for k in range(3)];recessions=[]
  for axis in [0,1]:
   plane_axis=1-axis;plane=(lo[plane_axis]+hi[plane_axis])/2;values=[]
   for edge in mesh.edges:
    a,b=[mesh.vertices[i].co for i in edge.vertices];da,db=a[plane_axis]-plane,b[plane_axis]-plane
    if da*db>0 or abs(da-db)<1e-12:continue
    t=da/(da-db);values.append(a.lerp(b,t)[axis])
   assert values;recessions += [min(values)-lo[axis],hi[axis]-max(values)]
  rows.append({'file':filename,'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'object':o.name,'midline_projected_silhouette_recession_m':recessions,'gross_projected_outline_gate_pass':max(recessions)<.015,'scope':'exact intersections of evaluated mesh edges with central X/Y planes;extrema across all Z. Separate from an equatorial cross-section or photo acceptance.'});ev.to_mesh_clear()
(ref/'pillow_projected_outline_audit.json').write_text(json.dumps({'prototypes':rows,'photorealism_accepted':False},indent=2));print(json.dumps(rows,indent=2))
