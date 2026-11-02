"""Actualsavedleaf apertureandsampledswing,retainedotherdoors;notglobalnav/photo."""
import bpy,json,hashlib,sys,argparse,math,numpy as np
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
pa=argparse.ArgumentParser();pa.add_argument('--revision',type=int,required=True);args=pa.parse_args(sys.argv[sys.argv.index('--')+1:]);r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';s=r/f'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r{args.revision}.blend';out=d/f'calibrated_leaf_saved_audit_r{args.revision}.json';assert not out.exists();meta=json.loads((d/f'realism_refinement_r{args.revision}.json').read_text());sha=hashlib.sha256(s.read_bytes()).hexdigest();assert sha==meta['candidate_sha256'];bpy.ops.wm.open_mainfile(filepath=str(s));o=bpy.data.objects[meta['object']];c=bpy.data.objects[meta['before']['casings'][0]['object']];dg=bpy.context.evaluated_depsgraph_get();rows=[]
for rec in json.loads((d/'private_conference_partition_probe_r93.json').read_text())['door_geometry_poses']:
 if rec['object']==o.name:continue
 ob=bpy.data.objects[rec['object']];h=hashlib.sha256()
 for coll,field,count,dtype in [(ob.data.vertices,'co',len(ob.data.vertices)*3,np.float32),(ob.data.loops,'vertex_index',len(ob.data.loops),np.int32),(ob.data.polygons,'loop_total',len(ob.data.polygons),np.int32),(ob.data.polygons,'material_index',len(ob.data.polygons),np.int32)]:
  arr=np.empty(count,dtype=dtype);coll.foreach_get(field,arr);h.update(arr.tobytes())
 rows.append({'object':ob.name,'unchanged':h.hexdigest()==rec['raw_geometry_sha256'] and [list(v) for v in ob.matrix_world]==rec['matrix_world'] and [m.name if m else None for m in ob.data.materials]==rec['materials']})
pts=[o.matrix_world@v.co for v in o.data.vertices];faces=[list(f.vertices) for f in o.data.polygons];bodyids={i for f in o.data.polygons if f.material_index==0 for i in f.vertices};body=[pts[i] for i in bodyids];corr=meta['closed_width_and_sweep_correction'];pin=Vector(corr['hinge_pin_world']);angle=math.radians(corr['open_to_closed_rotation_deg']);poses=[[pin+Matrix.Rotation(angle*k/36,4,'Z')@(p-pin) for p in pts] for k in range(37)];swept_lo=Vector([min(p[k] for pp in poses for p in pp) for k in range(3)]);swept_hi=Vector([max(p[k] for pp in poses for p in pp) for k in range(3)]);visible=set()
def collect(layer,blocked=False):
 blocked=blocked or layer.exclude or layer.collection.hide_render
 if not blocked:visible.update(x.name for x in layer.collection.objects)
 for child in layer.children:collect(child,blocked)
collect(bpy.context.view_layer.layer_collection);trees={};kinds={}
for ob in bpy.context.scene.objects:
 if ob==o or ob.type!='MESH' or ob.hide_render or ob.name not in visible:continue
 kind='casing' if ob==c else 'structure' if ob.name.endswith(('.wall','.exterior')) else None
 current=ob
 while current and kind is None:
  if current.get('audit_kind')=='furniture':kind='furniture';break
  current=current.parent
 if kind is None:continue
 bbox=[ob.matrix_world@Vector(v) for v in ob.bound_box];lo=Vector([min(p[k] for p in bbox) for k in range(3)]);hi=Vector([max(p[k] for p in bbox) for k in range(3)])
 if not all(swept_hi[k]>=lo[k] and hi[k]>=swept_lo[k] for k in range(3)):continue
 ev=ob.evaluated_get(dg);m=ev.to_mesh();trees[ob.name]=BVHTree.FromPolygons([ob.matrix_world@v.co for v in m.vertices],[list(f.vertices) for f in m.polygons]);kinds[ob.name]=kind;ev.to_mesh_clear()
assert c.name in trees;ct=trees[c.name];floor=meta['placement_correction']['floor_z'];slices=[];cx=(corr['aperture_left_right'][0]+corr['aperture_left_right'][1])/2
for old in meta['placement_correction']['aperture_slices']:
 q=Vector((cx,old['y'],floor+1.2));head=ct.ray_cast(q,Vector((0,0,1)),2)[0];left=ct.ray_cast(q,Vector((-1,0,0)),1)[0];right=ct.ray_cast(q,Vector((1,0,0)),1)[0];assert all(x is not None for x in [head,left,right]);slices.append({'y':old['y'],'head_z':head.z,'left_x':left.x,'right_x':right.x})
closedbody=[poses[-1][i] for i in bodyids];left=max(x['left_x'] for x in slices);right=min(x['right_x'] for x in slices);closedlo=min(p.x for p in closedbody);closedhi=max(p.x for p in closedbody);sweep=[]
for k,points in enumerate(poses):
 tree=BVHTree.FromPolygons(points,faces);hits=[]
 for name,other in trees.items():
  pairs=len(tree.overlap(other))
  if pairs:hits.append({'object':name,'kind':kinds[name],'triangle_surface_pairs':pairs})
 sweep.append({'fraction':k/36,'hits':hits})
checks={'other11doors_unchanged':len(rows)==11 and all(x['unchanged'] for x in rows),'native_leaf26_lever1020_faces':len(o.data.polygons)==1046 and sum(f.material_index==0 for f in o.data.polygons)==26,'undercut_8mm':abs(min(p.z for p in body)-floor-.008)<1e-5,'headgap_4mm':abs(min(x['head_z'] for x in slices)-max(p.z for p in body)-.004)<1e-5,'nominal_closed_left_clearance_atleast2p5mm':closedlo-left>=.0025,'nominal_closed_right_clearance_atleast2p5mm':right-closedhi>=.0025,'sampled37pose_structure_furniture_casing_surface_clear':all(not x['hits'] for x in sweep)};errors=[k for k,v in checks.items() if not v];out.write_text(json.dumps({'source':str(s),'source_sha256':sha,'checks':checks,'errors':errors,'pass':not errors,'aperture_slices':slices,'closed_leaf_left_right':[closedlo,closedhi],'closed_nominal_side_gaps_m':[closedlo-left,right-closedhi],'sweep_obstacles':[{'object':k,'kind':kinds[k]} for k in trees],'sweep':sweep,'other_doors':rows,'scope':'Savedmeasuredaperture/8mmundercut/4mmheadgap/nominalclosedsidefit and37discretemovingwholeleaf+levertrianglesurfacechecksagainstvisibleoverlappingnamedwalls/exteriors andtaggedfurniture/casing. Doesnotprovecontinuoussweep,allvolumecontainment/untaggedprops,hinge/latchassembly,globalnav orphotoacceptance.','photorealism_accepted':False},indent=2));print('CALIBRATED_LEAF_SAVED_AUDIT',len(errors),errors,flush=True);assert not errors,errors
