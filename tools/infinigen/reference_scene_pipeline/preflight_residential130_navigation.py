"""Whole ground-floor counterexample screen from all enabled render surfaces.

Raster results identify where exact continuous route checks are needed, never certify navigation.
"""
import bpy,json,sys,hashlib,math,time
import numpy as np
import cv2
from pathlib import Path
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from physical_scene_geometry import render_mesh_candidates,evaluated_surface
d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'navigation130_preflight';out.mkdir(exist_ok=True);src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r130_draft.blend';bpy.ops.wm.open_mainfile(filepath=str(src));objects,inventory=render_mesh_candidates();(out/'mesh_inventory.json').write_text(json.dumps(inventory,indent=2));pitch=.025;origin=np.array([-.5,-.5]);shape=(761,901);floor=np.zeros(shape,np.uint8);blocked=np.zeros(shape,np.uint8);fz=.1145347;low=fz+.02;high=fz+1.75;stats=[]
def pix(p):return np.rint((np.asarray(p)[:,:2]-origin)/pitch).astype(np.int32)
def clip(poly,z,above):
 result=[]
 for a,b in zip(poly,poly[1:]+poly[:1]):
  ia=a[2]>=z if above else a[2]<=z;ib=b[2]>=z if above else b[2]<=z
  if ia:result.append(a)
  if ia!=ib:result.append(a+(b-a)*((z-a[2])/(b[2]-a[2])))
 return result
for number,o in enumerate(objects):
 points,triangles,used=evaluated_surface(o);pts=np.asarray(points);counts={'object':o.name,'triangles':len(triangles),'floor_triangles':0,'obstacle_polygons':0}
 if not len(pts) or not triangles:stats.append(counts);continue
 bb=pts[list(used)];lo=bb.min(0);hi=bb.max(0)
 if hi[0]<-.5 or lo[0]>22 or hi[1]<-.5 or lo[1]>18.5:stats.append(counts);continue
 tri=np.asarray(triangles,np.int32);t=pts[tri];zs=t[:,:,2];floor_ids=np.flatnonzero(np.max(np.abs(zs-fz),axis=1)<=.003)
 for idx in floor_ids:
  a=t[idx];n=np.cross(a[1]-a[0],a[2]-a[0]);length=np.linalg.norm(n)
  if length>1e-10 and n[2]/length>.8:cv2.fillPoly(floor,[pix(a)],1);counts['floor_triangles']+=1
 ids=np.flatnonzero((zs.max(1)>=low)&(zs.min(1)<=high))
 for idx in ids:
  poly=clip(list(t[idx]),low,True);poly=clip(poly,high,False) if poly else []
  if len(poly)>=3:cv2.fillPoly(blocked,[pix(poly)],1);counts['obstacle_polygons']+=1
 stats.append(counts)
 if number%100==0:print('NAV130_MESH',number,len(objects),flush=True)
free=(floor & (1-blocked)).astype(np.uint8);dist=cv2.distanceTransform(free,cv2.DIST_L2,cv2.DIST_MASK_PRECISE)*pitch;radius=.3+pitch*math.sqrt(2)/2;valid=(dist>=radius).astype(np.uint8);num,labels=cv2.connectedComponents(valid,connectivity=8);rooms=json.loads((d/'room_mapping_candidate_r119.json').read_text());seeds=[]
for unit,point in [(101,(8.3,6.75)),(102,(13.2,6.75))]:
 xx,yy=pix([point])[0];ys,xs=np.nonzero(valid);ds=(xs-xx)**2+(ys-yy)**2;idx=int(ds.argmin());y=int(ys[idx]);x=int(xs[idx]);offset=math.sqrt(float(ds[idx]))*pitch;seeds.append({'unit':unit,'requested_xy_m':point,'nearest_valid_xy_m':list(origin+np.array([x,y])*pitch),'seed_offset_m':offset,'component':int(labels[y,x]),'seed_reliable':offset<=.5})
rows=[]
for key,room in rooms.items():
 mask=np.zeros(shape,np.uint8);cv2.fillPoly(mask,[pix(room['polygon_m'])],1);components,ns=np.unique(labels[(mask>0)&(valid>0)],return_counts=True);areas={int(k):int(n)*pitch*pitch for k,n in zip(components,ns) if k};unit=101 if key.startswith('101') else 102 if key.startswith('102') else None;seed=next((s for s in seeds if s['unit']==unit),None);area=areas.get(seed['component'],0) if seed and seed['seed_reliable'] else None;rows.append({'room':key,'room_id':room.get('room_id'),'valid_center_area_m2':sum(areas.values()),'components_area_m2':areas,'connected_to_unit_seed_area_m2':area,'needs_exact_followup':area is None or area<.01})
image=np.full((*shape,3),245,np.uint8);image[floor>0]=[220,220,220];image[blocked>0]=[70,70,90];image[valid>0]=[120,190,100];cv2.imwrite(str(out/'ground_floor_screen.png'),np.flipud(image));np.savez_compressed(out/'raster.npz',floor=floor,blocked=blocked,valid=valid,labels=labels,origin=origin,pitch=pitch);result={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'included_meshes':len(objects),'excluded_meshes':sum(not x['included'] for x in inventory),'pitch_m':pitch,'finished_floor_z_m':fz,'body_vertical_band_m':[low,high],'body_nominal_width_m':.6,'screen_radius_with_half_cell_diagonal_m':radius,'components':num-1,'seeds':seeds,'rooms':rows,'mesh_statistics':stats,'navigation_certified':False,'scope':'All enabled render mesh evaluated triangles, loose vertices excluded. All actual upward surfaces within3mm finished ground floor support. Height-clipped obstacles projected at25mm cells; raster conservative margin but not exact continuous body/door motion. Camera visibility ignored; glass conservatively solid. Texture opacity, render-time displacement/instances, stair climbing and all upper levels unverified. Room sidecar119 is provisional; disconnected cells trigger exact follow-up, not automatic layout changes.'};(out/'result.json').write_text(json.dumps(result,indent=2));print('NAV130_SCREEN_COMPLETE',[(x['room'],x['connected_to_unit_seed_area_m2']) for x in rows],flush=True)
