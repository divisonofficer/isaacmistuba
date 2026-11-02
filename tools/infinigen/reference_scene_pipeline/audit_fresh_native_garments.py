"""Compare untouched factory, fitted factory and decimation before another cloth solve."""
import bpy,sys,math,json,os,datetime
from pathlib import Path
from mathutils import Matrix,Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'tools/infinigen'),str(ROOT/'modules/infinigen')]
from room_planner import proc_assets as pa
ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.read_factory_settings(use_empty=True)
rows=[]
def audit(o):
 m=o.data;polys=[list(f.vertices) for f in m.polygons];tree=BVHTree.FromPolygons([v.co for v in m.vertices],polys);sets=[set(p) for p in polys];coords=[{tuple(round(float(x),7) for x in m.vertices[k].co) for k in p} for p in polys]
 pairs=[(i,j) for i,j in tree.overlap(tree) if j>i and not sets[i]&sets[j] and not coords[i]&coords[j]]
 return {'vertices':len(m.vertices),'faces':len(polys),'candidate_nonadjacent_self_overlap_pairs':len(pairs),'sample_pairs':pairs[:8],'zero_area_faces':sum(f.area<1e-12 for f in m.polygons)}
for i in range(6):
 attrs={'width':[.40,.42,.39,.43,.41,.40][i],'size':[.51,.55,.50,.57,.53,.56][i],'size_neck':[.025,.032,.028,.030,.026,.035][i],'sleeve_width':.095 if i<4 else .105,'sleeve_length':.09 if i<4 else .23,'sleeve_angle':.60,'thickness':.022}
 o=pa._cloth('shirt','ShirtFactory',811330+i,**attrs);assert o is not None
 raw=audit(o);o.data.transform(Matrix.Rotation(math.pi/2,4,'X'));bpy.context.view_layer.objects.active=o;o.select_set(True)
 md=o.modifiers.new('Same_decimation_as_original_pipeline','DECIMATE');md.ratio=.3;bpy.ops.object.modifier_apply(modifier=md.name)
 reduced=audit(o);rows.append({'pattern':i,'factory_seed':811330+i,'parameters':attrs,'factory':raw,'decimated':reduced})
 (ref/'fresh_native_garment_initial_audit.json').write_text(json.dumps({'pid':os.getpid(),'phase':'complete' if i==5 else 'auditing','patterns':rows,'scope':'BVH overlap candidate count;not signed penetration depth,not photo acceptance;no cloth solve performed'},indent=2))
 print('FRESH_PATTERN',i,raw['candidate_nonadjacent_self_overlap_pairs'],reduced['candidate_nonadjacent_self_overlap_pairs'],flush=True)
 bpy.data.objects.remove(o,do_unlink=True)
