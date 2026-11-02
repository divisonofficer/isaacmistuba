"""Bounded actual saved native shared-wall guard; no scene mutation or photo acceptance."""
import argparse,bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
try:from shapely.geometry import Polygon
except ImportError:
 sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages');from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely import make_valid
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--keep',default='office_0/0.exterior');p.add_argument('--other',default='office_0/1.exterior');p.add_argument('--plane-y',type=float,default=5.5);a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]);bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(a.blend.resolve()),link=False) as (source,dest):
 assert a.keep in source.objects and a.other in source.objects;dest.objects=[a.keep,a.other]
objects=dest.objects
for o in objects:bpy.context.scene.collection.objects.link(o)
bpy.context.view_layer.update();planes=[]
for o in objects:
 shapes=[]
 for face in o.data.polygons:
  vs=[o.matrix_world@o.data.vertices[i].co for i in face.vertices]
  if max(abs(v.y-a.plane_y) for v in vs)<=1e-5:
   g=make_valid(Polygon([(v.x,v.z) for v in vs]))
   if g.area>1e-10:shapes.append(g)
 planes.append(unary_union(shapes))
overlap=planes[0].intersection(planes[1]).area;errors=[]
if planes[0].area<.01:errors.append('Retained physical wall surface missing; hiding/deleting both sides does not pass.')
if overlap>1e-7:errors.append('Opposing saved native wall coverage remains coincident in the bounded shared plane.')
d={'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'objects':[a.keep,a.other],'plane_y_m':a.plane_y,'projected_areas_m2':[x.area for x in planes],'overlap_area_m2':overlap,'maximum_allowed_overlap_m2':1e-7,'errors':errors,'pass':not errors,'photorealism_accepted':False,'scope':'Actual two saved raw native wall meshes, world transforms, bounded plane only. No global duplicate-surface or whole-scene physical/photo certification.'};a.out.write_text(json.dumps(d,indent=2)+'\n');print(json.dumps({'pass':not errors,'overlap_area_m2':overlap,'errors':errors}),flush=True)
if errors:raise SystemExit(2)
