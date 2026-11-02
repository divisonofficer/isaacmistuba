"""Actual evaluated leaf/casing surface contact;not a full sweep/containment proof."""
import bpy,json,sys,argparse,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';s=r/f'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r{a.revision}.blend';out=d/f'conference_leaf_casing_probe_r{a.revision}.json';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(s));door=bpy.data.objects['PanelDoorFactory(4643175).spawn_asset(6)'];casing=bpy.data.objects['DoorCasingFactory(4643175).spawn_asset(6)'];dg=bpy.context.evaluated_depsgraph_get();ev=casing.evaluated_get(dg);m=ev.to_mesh();cp=[casing.matrix_world@v.co for v in m.vertices];cf=[list(f.vertices) for f in m.polygons];ct=BVHTree.FromPolygons(cp,cf);ev.to_mesh_clear()
if a.revision==93:
 rec=json.loads((d/'native_door_components_r93.json').read_text());indices=rec['components'][0]['face_indices'];faces=[door.data.polygons[i] for i in indices]
else:faces=[f for f in door.data.polygons if f.material_index==0]
ids=sorted({v for f in faces for v in f.vertices});lookup={v:i for i,v in enumerate(ids)};pts=[door.matrix_world@door.data.vertices[i].co for i in ids];fs=[[lookup[i] for i in f.vertices] for f in faces];dt=BVHTree.FromPolygons(pts,fs);pairs=dt.overlap(ct);nearest=sorted([{'point':list(p),'casing_nearest':list(hit[0]),'distance_m':hit[3]} for p in pts if (hit:=ct.find_nearest(p))[0] is not None],key=lambda x:x['distance_m']);hits=[]
# Rays from either side oftheleaf nearhinge/center/latch atthreeheights,allnamedfixedcasinggeometry.
W=Vector((.0200638496,.9997987007,0));N=Vector((-.9997987007,.0200638496,0));meta=json.loads((d/'realism_refinement_r94.json').read_text());center=Vector(meta['fitting']['center_world']);width=meta['fitting']['matched_old_leaf_width_height'][0]
for along in [-width/2,-width/2+.01,0,width/2-.01,width/2]:
 for z in [.3,1.3,2.3]:
  q=center+W*along;q.z=z;row={'along_width_m':along,'height_m':z,'hits':[]}
  for sign in [-1,1]:
   origin=q+N*(.15*sign);hit=ct.ray_cast(origin,N*(-sign),.3)
   if hit[0] is not None:row['hits'].append({'origin_sign':sign,'hit':list(hit[0]),'distance_m':hit[3]})
  hits.append(row)
out.write_text(json.dumps({'source':str(s),'source_sha256':hashlib.sha256(s.read_bytes()).hexdigest(),'door':door.name,'casing':casing.name,'leaf_face_count':len(faces),'casing_evaluated_face_count':len(cf),'triangle_surface_intersection_pairs':len(pairs),'nearest_leaf_vertices_to_casing':nearest[:12],'casing_rays':hits,'scope':'Onecurrentpose evaluated triangle intersections andvertex-nearest distances/rays;not closedvolume/hinge/latch assembly orfullsweep/navigation acceptance.','photorealism_accepted':False},indent=2));print('LEAF_CASING_PROBE',a.revision,len(pairs),flush=True)
