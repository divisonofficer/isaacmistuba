"""Authored mixed-light graph/power and bounded emitter-clearance checks."""
import bpy,json,hashlib,sys,argparse
from pathlib import Path
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--revision',required=True,type=int)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:])
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
m=json.loads((D/f'realism_refinement_r{a.revision}.json').read_text());s=Path(m['candidate'])
sha=hashlib.sha256(s.read_bytes()).hexdigest();assert sha==m['candidate_sha256']
out=D/f'living102_mixed_saved_audit_r{a.revision}.json';assert not out.exists()
bpy.ops.wm.open_mainfile(filepath=str(s));c=m['unit102_lighting'];d=c['daylight_fill'];errors=[]
obj=bpy.data.objects[d['object']];em=next(n for n in obj.data.node_tree.nodes if n.type=='EMISSION')
bb=em.inputs['Color'].links[0].from_node if em.inputs['Color'].is_linked else None
direction=(obj.matrix_world.to_3x3()@Vector((0,0,-1))).normalized()
power=sum(bpy.data.objects[r['area_light']].data.energy for r in c['fixtures'])+obj.data.energy
checks={'area_energy_sum_matches_authored_budget':abs(power-c['replaced_area_power'])<1e-5,
    'warm_fraction_matches_budget':abs(sum(bpy.data.objects[r['area_light']].data.energy for r in c['fixtures'])/power-.4)<1e-6,
    'daylight_fraction_matches_budget':abs(obj.data.energy/power-.6)<1e-6,
    'daylight_5500K_active':bb is not None and bb.type=='BLACKBODY' and bb.inputs['Temperature'].default_value==5500,
    'daylight_node_multiplier_one':not em.inputs['Strength'].is_linked and em.inputs['Strength'].default_value==1,
    'not_portal':not obj.data.cycles.is_portal,
    'faces_inside_room':direction.dot(Vector((-1,0,0)))>.999,
    'source_position_matches':(obj.location-Vector(d['position'])).length<1e-5,
    'rectangle_dimensions_match':abs(obj.data.size-d['size_m'][0])<1e-5 and abs(obj.data.size_y-d['size_m'][1])<1e-5}
bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();rays=[]
for y,z in [(0,0),(-obj.data.size_y/2,-obj.data.size/2),(-obj.data.size_y/2,obj.data.size/2),(obj.data.size_y/2,-obj.data.size/2),(obj.data.size_y/2,obj.data.size/2)]:
    origin=obj.location+Vector((0,y,z));hit,point,normal,index,other,matrix=bpy.context.scene.ray_cast(dg,origin,direction,distance=.2)
    rays.append({'origin':list(origin),'first_200mm_hit':other.name if hit else None})
checks['central_emitter_ray_clear_200mm']=rays[0]['first_200mm_hit'] is None
for row in c['coves']:
    co=bpy.data.objects[row['object']]
    for mat in co.data.materials:
        bs=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
        node=bs.inputs['Emission Color'].links[0].from_node if bs.inputs['Emission Color'].is_linked else None
        if node is None or node.type!='BLACKBODY' or node.inputs['Temperature'].default_value!=3500:errors.append('Cove temperature:'+co.name)
        if abs(bs.inputs['Emission Strength'].default_value-row['emission_strength'])>1e-5:errors.append('Cove authored strength:'+co.name)
errors.extend(k for k,v in checks.items() if not v)
out.write_text(json.dumps({'source':str(s),'source_sha256':sha,'checks':checks,'emitter_sample_rays':rays,
    'total_area_power':power,'errors':errors,'pass':not errors,'photorealism_accepted':False,
    'scope':'Declared four practical lights40pct + window-side fill60pct AREA watt budget, active3500/5500K nodes, multiplier1,placement/direction and five bounded clearance rays. Equal AREA watts do not prove equal luminous flux, irradiance, exposure or photographic quality. Corner occlusions are reported, not blanket failures.'},indent=2))
assert not errors,errors
print('LIVING102_MIXED_SAVED_AUDIT',flush=True)
