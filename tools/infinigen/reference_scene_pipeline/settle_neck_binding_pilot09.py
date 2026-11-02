"""Controlled collar-band bending trial on exact pilot08 initial mesh/wire/pins.
Hypothesis only: rejected08 overlaps concentrate at neckline/shoulders. No integration.
"""
import bpy,json,math,hashlib,heapq,os
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ref=Path('/jarvis/project/robomituba/data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03');src=ref/'garment_roof_hanger_pilot08.blend';out=ref/'garment_neck_binding_settled09.blend';state=ref/'garment_neck_binding_settled09_job.json';assert not out.exists() and not state.exists();proof=json.loads((ref/'garment_roof_hanger_pilot08_preflight.json').read_text());assert proof['pass'] and len(proof['pin_contacts'])==12
bpy.ops.wm.open_mainfile(filepath=str(src));scene=bpy.context.scene;scene.frame_set(1);shirt=bpy.data.objects['Native_neck_clearance_fit_shirt'];wire=bpy.data.objects['Measured shoulder wire'];me=shirt.data;geometry_hash=hashlib.sha256(repr([tuple(v.co) for v in me.vertices]).encode()).hexdigest();edge_faces={tuple(sorted(e.vertices)):0 for e in me.edges};adj=[[] for _ in me.vertices]
for f in me.polygons:
 for key in f.edge_keys:edge_faces[tuple(sorted(key))]+=1
for e in me.edges:
 i,j=e.vertices;length=(me.vertices[i].co-me.vertices[j].co).length;adj[i].append((j,length));adj[j].append((i,length))
boundary={i for edge,n in edge_faces.items() if n==1 for i in edge};seeds=[i for i in boundary if abs(me.vertices[i].co.x)<.11 and me.vertices[i].co.z>-.10];assert len(seeds)>=4,('No unambiguous native neckline boundary',len(seeds));dist={i:0 for i in seeds};queue=[(0,i) for i in seeds];heapq.heapify(queue)
while queue:
 d,i=heapq.heappop(queue)
 if d!=dist[i]:continue
 for j,length in adj[i]:
  nd=d+length
  if nd<=.02 and nd<dist.get(j,math.inf):dist[j]=nd;heapq.heappush(queue,(nd,j))
band=shirt.vertex_groups.new(name='Measured_native_neck_binding_20mm');weights=[]
for i,d in dist.items():
 w=max(0,1-d/.02)
 if w>0:band.add([i],w,'REPLACE');weights.append({'vertex':i,'distance_from_neck_boundary_m':d,'weight':w})
assert len(weights)>len(seeds) and len(weights)<len(me.vertices)*.3
assert hashlib.sha256(repr([tuple(v.co) for v in me.vertices]).encode()).hexdigest()==geometry_hash
pins=shirt.vertex_groups['Actual_roof_contacts'];actual_pins=sorted(v.index for v in me.vertices for g in v.groups if g.group==pins.index and g.weight>.999);assert actual_pins==sorted(p['index'] for p in proof['pin_contacts'])
wire.modifiers.new('Measured_wire_collision','COLLISION');wire.collision.thickness_inner=.001;wire.collision.thickness_outer=.001;wire.collision.cloth_friction=2.5
cm=shirt.modifiers.new('Supported_native_cloth','CLOTH');st=cm.settings;st.quality=12;st.mass=.18/len(me.vertices);st.tension_stiffness=25;st.compression_stiffness=25;st.shear_stiffness=12;st.bending_stiffness=.65;st.air_damping=4;st.vertex_group_mass=pins.name;st.vertex_group_bending=band.name;st.bending_stiffness_max=3.0;cs=cm.collision_settings;cs.use_collision=True;cs.distance_min=.0015;cs.collision_quality=8;cs.use_self_collision=True;cs.self_distance_min=.001;cs.self_friction=1;cm.point_cache.frame_start=1;cm.point_cache.frame_end=60
initial=[max(v.co[k] for v in me.vertices)-min(v.co[k] for v in me.vertices) for k in range(3)];d={'pid':os.getpid(),'phase':'simulating','frame':0,'frames':60,'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'initial_extent_m':initial,'initial_geometry_sha256':geometry_hash,'actual_total_mass_kg':float(st.mass)*len(me.vertices),'neck_boundary_vertices':seeds,'neck_band_weights':weights,'fixed_contact_indices':actual_pins,'controlled_change':'Only local bending weights within20mm geodesic distance of native neckline boundary, max3.0 vsbase0.65. Same initial08 geometry/wire/pins, total mass, stiffness elsewhere, collision margins andquality.','hypothesis':'380/382 overlap candidates in rejected08 locate at upper neck/shoulders; test local neck-binding stiffness rather than global solver changes. Not calibrated fabric measurement.','geometry_gate_pass':False,'room_integration':False,'photorealism_accepted':False}
def save():state.write_text(json.dumps(d,indent=2))
save()
for frame in range(1,61):
 scene.frame_set(frame);ev=shirt.evaluated_get(bpy.context.evaluated_depsgraph_get());mesh=ev.to_mesh();extent=[max(v.co[k] for v in mesh.vertices)-min(v.co[k] for v in mesh.vertices) for k in range(3)];ev.to_mesh_clear();d.update(frame=frame,current_extent_m=extent)
 if extent[2]<.8*initial[2] or max(extent)>2*max(initial):d.update(phase='rejected_extent_failure');save();raise RuntimeError('Cloth extent collapsed or exploded')
 if frame%5==0:save();print('NECK_BINDING_FRAME',frame,extent,flush=True)
bpy.ops.object.select_all(action='DESELECT');shirt.select_set(True);bpy.context.view_layer.objects.active=shirt;bpy.ops.object.modifier_apply(modifier=cm.name);pts=[v.co.copy() for v in shirt.data.vertices];polys=[list(f.vertices) for f in shirt.data.polygons];tree=BVHTree.FromPolygons(pts,polys);sets=[set(f) for f in polys];coords=[{tuple(round(float(x),7) for x in pts[k]) for k in f} for f in polys];pairs=[(i,j) for i,j in tree.overlap(tree) if j>i and not sets[i]&sets[j] and not coords[i]&coords[j]];wps=[Vector(p) for p in proof['wire_points']];lower=[]
for a,b in zip(wps[:-1],wps[1:]):
 length=(b-a).length;n=max(1,math.ceil(length/.0005));lower.append(min(tree.find_nearest(a.lerp(b,k/n))[3] for k in range(n+1))-length/n/2)
d.update(nonadjacent_overlap_candidates=len(pairs),minimum_wire_centreline_surface_distance_lower_bound_m=min(lower),wire_radius_m=.0022,geometry_gate_pass=not pairs and min(lower)>=.0045);d['phase']='geometry_pass_visual_review_pending' if d['geometry_gate_pass'] else 'baked_geometry_failed_no_integration';bpy.ops.wm.save_as_mainfile(filepath=str(out));save();print('FINAL',d['phase'],len(pairs),min(lower),flush=True)
