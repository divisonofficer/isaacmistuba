"""Check baked shoulder pins against their intended physical wire positions and their original material points."""
import bpy,json,hashlib,math,bisect
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';before=base/'scene_candidate_r37.blend';after=base/'scene_candidate_r40.blend';bpy.ops.wm.open_mainfile(filepath=str(before));patterns={}
for i in range(6):
 o=next(o for o in bpy.data.objects if o.get('program_key')==f'101_native_garment_0_{i}');points=[v.co.copy() for v in o.data.vertices]
 for q in points:q.y+=.0008*math.sin(20*q.x+i)*math.sin(15*q.z)+.0004*math.cos(31*q.z-9*q.x+i)
 upper=sorted((abs(q.x),q.z) for q in points if q.z>-.16);keys=[x for x,z in upper]
 for q in points:
  ax=abs(q.x)
  if .07<ax<.21 and q.z>-.24:
   candidates=[z for x,z in upper[bisect.bisect_right(keys,ax-.012):bisect.bisect_left(keys,ax+.012)]]
   if candidates:q.z+=min(0,-.075*min(ax/.18,1)+.004-max(candidates))*min(1,max(0,(q.z+.24)/.12))
 patterns[i]=points
bpy.ops.wm.open_mainfile(filepath=str(after));rows=[]
for i in range(6):
 o=next(o for o in bpy.data.objects if o.get('program_key')==f'101_native_garment_0_{i}');pins=[v for v in o.data.vertices if any(g.group==1 and g.weight>.99 for g in v.groups)];samples=[]
 for v in pins:
  q=patterns[i][v.index];side=1 if q.x>0 else -1;a=Vector((side*.18,0,-.075));b=Vector((0,0,0));axis=(b-a).normalized();t=max(0,min((q-a).dot(axis),(b-a).length));center=a+axis*t;radial=Vector((0,.5 if q.y>=0 else -.5,1));radial-=axis*radial.dot(axis);target=center+radial.normalized()*.0037;samples.append({'vertex':v.index,'initial_local':list(q),'target_local':list(target),'baked_local':list(v.co),'initial_snap_distance_m':(q-target).length,'baked_pin_residual_m':(v.co-target).length})
 rows.append({'pattern':i,'baked_pin_count':len(pins),'maximum_initial_snap_m':max((s['initial_snap_distance_m'] for s in samples),default=None),'maximum_baked_residual_m':max((s['baked_pin_residual_m'] for s in samples),default=None),'samples':samples})
result={'source_before':str(before),'source_after':str(after),'scope':'actual baked pin coordinates,not a visual realism verdict; native40 pin group index1','patterns':rows};(ref/'shoulder_contact_audit_r40.json').write_text(json.dumps(result,indent=2));print(json.dumps([{k:v for k,v in r.items() if k!='samples'} for r in rows]),flush=True)
