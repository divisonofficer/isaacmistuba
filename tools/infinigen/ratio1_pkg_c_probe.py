import bpy,json,sys
from pathlib import Path
from mathutils import Vector
p=Path('/tmp/claude-0/s/codex_pkgs/pkg_c');p.mkdir(parents=True,exist_ok=True)
a=[]
for o in bpy.data.objects:
 if o.type=='MESH' and (o.name.endswith('.floor') or o.name.startswith(('CheckoutCounter','CafeCounter','Gondola','HssdPlant','Real_hssd','Real_planter','door','ConvImpulse','ConvCoffee'))):
  q=[o.matrix_world@Vector(c) for c in o.bound_box];lo=[min(v[i] for v in q) for i in range(3)];hi=[max(v[i] for v in q) for i in range(3)]
  a.append({'name':o.name,'lo':lo,'hi':hi,'mats':[m.name for m in o.data.materials if m]})
(p/'probe.json').write_text(json.dumps({'blend':bpy.data.filepath,'objects':a,'cameras':[o.name for o in bpy.data.objects if o.type=='CAMERA']},indent=2))
