"""Correct-mass cloth on preflighted curved wire; no garment warping, no room integration."""
import bpy,json,os,math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba/data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03');out=r/'garment_roof_hanger_settled08.blend';assert not out.exists();proof=json.loads((r/'garment_roof_hanger_pilot08_preflight.json').read_text());assert proof['pass'] and len(proof['pin_contacts'])==12;assert proof['minimum_wire_centreline_surface_distance_lower_bound_m']>=proof['wire_radius_m']+proof['cloth_distance_min_m']+proof['collider_thickness_outer_m'];assert all(x['wire_gap_m']>=.0025 for x in proof['pin_contacts'])
bpy.ops.wm.open_mainfile(filepath=str(r/'garment_roof_hanger_pilot08.blend'));s=bpy.context.scene;s.frame_set(1);shirt=bpy.data.objects['Native_neck_clearance_fit_shirt'];wire=bpy.data.objects['Measured shoulder wire'];initial=[max(v.co[k] for v in shirt.data.vertices)-min(v.co[k] for v in shirt.data.vertices) for k in range(3)]
wire.modifiers.new('Measured_wire_collision','COLLISION');wire.collision.thickness_inner=.001;wire.collision.thickness_outer=.001;wire.collision.cloth_friction=2.5
cm=shirt.modifiers.new('Supported_native_cloth','CLOTH');st=cm.settings;st.quality=12;st.mass=.18/len(shirt.data.vertices);st.tension_stiffness=25;st.compression_stiffness=25;st.shear_stiffness=12;st.bending_stiffness=.65;st.air_damping=4;st.vertex_group_mass='Actual_roof_contacts';cs=cm.collision_settings;cs.use_collision=True;cs.distance_min=.0015;cs.collision_quality=8;cs.use_self_collision=True;cs.self_distance_min=.001;cs.self_friction=1;cm.point_cache.frame_start=1;cm.point_cache.frame_end=60
state=r/'garment_roof_hanger_settled08_job.json';d={'pid':os.getpid(),'phase':'simulating','initial_extent_m':initial,'actual_total_mass_kg':float(st.mass)*len(shirt.data.vertices),'frame':0,'frames':60,'room_integration':False,'photorealism_accepted':False}
for frame in range(1,61):
 s.frame_set(frame);ev=shirt.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh();extent=[max(v.co[k] for v in me.vertices)-min(v.co[k] for v in me.vertices) for k in range(3)];ev.to_mesh_clear();d.update(frame=frame,current_extent_m=extent)
 if extent[2]<.8*initial[2] or max(extent)>2*max(initial):
  d.update(phase='rejected_extent_failure');state.write_text(json.dumps(d,indent=2));raise RuntimeError('Cloth extent collapsed or exploded')
 if frame%5==0:state.write_text(json.dumps(d,indent=2));print('ROOF_CLOTH_FRAME',frame,extent,flush=True)
bpy.ops.object.select_all(action='DESELECT');shirt.select_set(True);bpy.context.view_layer.objects.active=shirt;bpy.ops.object.modifier_apply(modifier=cm.name)
points=[v.co.copy() for v in shirt.data.vertices];polys=[list(f.vertices) for f in shirt.data.polygons];tree=BVHTree.FromPolygons(points,polys);sets=[set(f) for f in polys];coords=[{tuple(round(float(x),7) for x in points[k]) for k in f} for f in polys];overlap=[(i,j) for i,j in tree.overlap(tree) if j>i and not sets[i]&sets[j] and not coords[i]&coords[j]];wps=[Vector(p) for p in proof['wire_points']];lower=[]
for a,b in zip(wps[:-1],wps[1:]):
 length=(b-a).length;n=max(1,math.ceil(length/.0005));nearest=min(tree.find_nearest(a.lerp(b,k/n))[3] for k in range(n+1));lower.append(nearest-length/n/2)
d.update(phase='baked_geometry_requires_gate_decision',nonadjacent_overlap_candidates=len(overlap),minimum_wire_centreline_surface_distance_lower_bound_m=min(lower),wire_radius_m=.0022,geometry_gate_pass=not overlap and min(lower)>=.0045)
d['phase']='geometry_pass_visual_review_pending' if d['geometry_gate_pass'] else 'baked_geometry_failed_no_integration';d['initial_preflight']=proof;d['hypothesis']='Native neckline retained;central apex60mm to38mm chosen by measured lip clearance. Same total mass/solver/contact protocol as04. Initial success isnot settled geometry orvisual success.';bpy.ops.wm.save_as_mainfile(filepath=str(out));state.write_text(json.dumps(d,indent=2));print(json.dumps(d),flush=True)
