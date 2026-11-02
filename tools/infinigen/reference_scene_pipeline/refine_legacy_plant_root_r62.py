"""Gather existing outdoor-grown root/base geometry into its soil footprint;canopy unchanged."""
import bpy,numpy as np,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3]
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
src=base/'scene_candidate_r61.blend';out=base/'scene_candidate_r62.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update()
plant=bpy.data.objects['Office02_native_plant_2'];soil=next(o for o in bpy.data.objects if o.get('program_key')=='soil_2');pot=next(o for o in bpy.data.objects if o.get('program_key')=='pot_2');plant.data=plant.data.copy()
sp=np.asarray([list(soil.matrix_world@v.co) for v in soil.data.vertices]);center=(sp[:,:2].min(0)+sp[:,:2].max(0))/2;limit=(sp[:,0].max()-sp[:,0].min())/2-.006
pp=[pot.matrix_world@v.co for v in pot.data.vertices];lip=max(v.z for v in pp);pt=BVHTree.FromPolygons(pp,[list(f.vertices) for f in pot.data.polygons])
local=np.asarray([list(v.co) for v in plant.data.vertices]);M=np.asarray(plant.matrix_world);world=local@M[:3,:3].T+M[:3,3];before=world.copy();inv=np.linalg.inv(M);faces=[list(f.vertices) for f in plant.data.polygons];attempts=[]
for above_lip in [.02,.04,.06]:
 start=lip+above_lip;end=start+.08;t=np.clip((before[:,2]-start)/(end-start),0,1);weight=1-t*t*(3-2*t);xy=before[:,:2]-center;radius=np.linalg.norm(xy,axis=1);reduction=weight*np.maximum(0,radius-limit);ratio=1-reduction/np.maximum(radius,1e-12);world=before.copy();world[:,:2]=center+xy*ratio[:,None]
 tree=BVHTree.FromPolygons([Vector(v) for v in world],faces);n=len(tree.overlap(pt));attempts.append({'full_constraint_height_above_rim_m':above_lip,'plant_pot_surface_intersections':n})
 if n==0:break
assert n==0,attempts
coords=world@inv[:3,:3].T+inv[:3,3]
plant.data.vertices.foreach_set('co',coords.astype(np.float32).ravel());plant.data.update();bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r62.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'scope':'Existing plant_2 mesh base XY only;pot/soil/plant pose,other scene andlighting unchanged','soil_center_xy_m':center.tolist(),'constrained_base_radius_m':float(limit),'identity_above_world_z_m':end,'upper_vertices_unchanged':bool(np.array_equal(before[before[:,2]>=end],world[before[:,2]>=end])),'maximum_vertex_displacement_m':float(np.linalg.norm(world-before,axis=1).max()),'modified_vertices':int((np.linalg.norm(world-before,axis=1)>1e-8).sum()),'plant_pot_checks':attempts,'photorealism_accepted':False,'requires':'Saved root/support audit;exact nearby external mesh checks andsame-camera root close comparison;full scene views remain required'},indent=2));print('SAVED',out,attempts,flush=True)
