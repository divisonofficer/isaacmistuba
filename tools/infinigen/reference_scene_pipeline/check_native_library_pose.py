"""Actual media library append comparison: dependency evaluation before reading world pose."""
import bpy,json,sys
from pathlib import Path
from mathutils import Vector
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';scope=json.loads((d/'native_media_products/scope.json').read_text());e=next(x for x in scope['assets'] if x['id'].startswith('HSSD_f359'));studio=scope['source'];rows=[]
for evaluated in [False,True]:
 bpy.ops.wm.read_factory_settings(use_empty=True)
 with bpy.data.libraries.load(studio,link=False) as (available,loaded):loaded.objects=e['objects'].copy()
 objs=loaded.objects
 for o in objs:bpy.context.scene.collection.objects.link(o)
 if evaluated:bpy.context.view_layer.update()
 for o in objs:
  M=o.matrix_world.copy();o.parent=None;o.matrix_world=M
 bpy.context.view_layer.update();ps=[o.matrix_world@v.co for o in objs for v in o.data.vertices];dims=[max(p[k] for p in ps)-min(p[k] for p in ps) for k in range(3)];rows.append({'evaluate_before_capture':evaluated,'dimensions_xyz_m':dims,'native_dimensions_match':max(abs(x-y) for x,y in zip(dims,e['actual_dimensions_xyz_m']))<1e-5})
(d/'native_media_products/library_pose_preflight.json').write_text(json.dumps({'source':studio,'rows':rows,'scope':'Actual native TV3-part library append into empty Blender scene, capture world pose with/without prior dependency graph update, unlink parents, evaluate and compare native width/depth/height. No room/photo acceptance.'},indent=2));print('LIBRARY_POSE_PREFLIGHT',rows,flush=True);assert rows[1]['native_dimensions_match']
