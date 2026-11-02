import bpy,bmesh,json
from pathlib import Path
r=Path(__file__).resolve().parents[3];p=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/wc109_trap_pilot_v7';bpy.ops.wm.open_mainfile(filepath=str(p/'candidate.blend'));bm=bmesh.new();bm.from_mesh(bpy.data.objects['NativeFullTankWC100'].data);edges=[e for e in bm.edges if e.is_boundary];groups=[]
while edges:
 group={edges.pop()};verts={v for e in group for v in e.verts};changed=True
 while changed:
  more={e for e in edges if any(v in verts for v in e.verts)};changed=bool(more);group|=more;verts|={v for e in more for v in e.verts};edges=[e for e in edges if e not in more]
 lo=[min(v.co[k] for v in verts) for k in range(3)];hi=[max(v.co[k] for v in verts) for k in range(3)];groups.append({'edges':len(group),'min':lo,'max':hi,'perimeter_m':sum(e.calc_length() for e in group),'each_vertex_degree2':all(sum(v in e.verts for e in group)==2 for v in verts)})
(p/'boundary_probe.json').write_text(json.dumps(groups,indent=2));print(json.dumps(groups));bm.free()
