"""Read-only current structural shell and window transformation inventory."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];S=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r88.blend';D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';O=D/'east_opening_structure_r88.json';assert not O.exists();bpy.ops.wm.open_mainfile(filepath=str(S));rows=[];dg=bpy.context.evaluated_depsgraph_get()
for o in bpy.context.scene.objects:
 if o.name not in ['office_0/9.wall','office_0/9.exterior','kitchen_0/0.wall','kitchen_0/0.exterior','WindowFactory(3498).spawn_asset(13)','WindowFactory(3498).spawn_asset(14)','window.013','window.014']:continue
 if o.type!='MESH':continue
 ev=o.evaluated_get(dg);me=ev.to_mesh();verts=[o.matrix_world@v.co for v in me.vertices];east=[]
 for f in me.polygons:
  pts=[verts[i] for i in f.vertices]
  # Actual east facade near x+.08y=16; include all thickness surfaces.
  if all(14.8<p.x+.08*p.y<16.3 for p in pts):east.append({'vertices':[list(p) for p in pts],'material_index':f.material_index,'normal_world':list(o.matrix_world.to_3x3()@f.normal)})
 rows.append({'name':o.name,'matrix_world':[list(v) for v in o.matrix_world],'bounds_min':[min(p[k] for p in verts) for k in range(3)],'bounds_max':[max(p[k] for p in verts) for k in range(3)],'raw_faces':len(o.data.polygons),'evaluated_faces':len(me.polygons),'materials':[m.name if m else None for m in me.materials],'modifiers':[{'name':m.name,'type':m.type} for m in o.modifiers],'east_surface_faces':east});ev.to_mesh_clear()
O.write_text(json.dumps({'source':str(S),'source_sha256':hashlib.sha256(S.read_bytes()).hexdigest(),'read_only':True,'objects':rows,'scope':'Exact named east-side shell/window inventory, evaluated face positions and modifiers. No opening fit or geometry modification yet.'},indent=2)+'\n');print('EAST_STRUCTURE_WRITTEN',len(rows),flush=True)
