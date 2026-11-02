import bpy,json,math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];W=R/'out/infinigen_v2/kr_industrial_workshop_floor_06_48712506';source=W/'furnished_r3_entry.blend';bpy.ops.wm.open_mainfile(filepath=str(source));bpy.context.view_layer.update();inv=json.loads((W/'native_product_inventory_r3_entry.json').read_text());cache={};rows=[]
def tree(names):
 key=tuple(names)
 if key not in cache:
  vs=[];fs=[]
  for name in names:
   o=bpy.data.objects[name];o.data.calc_loop_triangles();k=len(vs);vs.extend([o.matrix_world@v.co for v in o.data.vertices]);fs.extend([[k+i for i in t.vertices]for t in o.data.loop_triangles])
  cache[key]=BVHTree.FromPolygons(vs,fs,all_triangles=True)
 return cache[key]
floornames=[o.name for o in bpy.data.objects if o.type=='MESH'and o.name.endswith('.floor')]
for p in inv['products']:
 ps=[]
 for name in p['objects']:
  o=bpy.data.objects[name];used={i for f in o.data.polygons for i in f.vertices};ps.extend([o.matrix_world@o.data.vertices[i].co for i in used])
 z=min(v.z for v in ps);bottom=[v for v in ps if v.z<z+.0005];assert bottom
 center=sum(bottom,Vector())/len(bottom);selected=[]
 for k in range(8):
  direction=Vector((math.cos(k*math.pi/4),math.sin(k*math.pi/4),0));q=max(bottom,key=lambda v:(v-center).dot(direction));
  if not any((q-r).length<1e-5 for r in selected):selected.append(q)
 supports=p.get('support_objects',floornames);bt=tree(supports);rays=[]
 for q in selected:
  hit,norm,face,distance=bt.ray_cast(q+Vector((0,0,.008)),Vector((0,0,-1)),.04);gap=None if hit is None else q.z-hit.z;rays.append({'native_bottom_vertex_world_m':list(q),'actual_support_hit_m':list(hit)if hit is not None else None,'vertical_gap_m':gap,'pass':gap is not None and abs(gap)<.002})
 rows.append({'label':p['label'],'objects':p['objects'],'native_bottom_z_m':z,'support_objects':supports,'rays':rays,'pass':all(r['pass']for r in rays)})
doc={'source':str(source),'rows':rows,'pass_actual_native_support':all(r['pass']for r in rows),'method':'Up to8directional extrema of actual faced native bottom vertices,0.5mm lowest band;downward actual support-mesh triangle BVH rays start8mm above,40mm range;abs gap<2mm. Genuine grinder bottoms tested against named real workbench;floor products against actual native floor+threshold union.','limitations':['Sampled actual contacts,not load-bearing structural certification or full contact manifold','No texture/mesh/scale edits'],'acceptance':False};(W/'actual_native_support_rays_r3_entry.json').write_text(json.dumps(doc,indent=2));print('WORKSHOP_ACTUAL_SUPPORT',doc['pass_actual_native_support'],[(r['label'],r['objects'],r['rays'])for r in rows if not r['pass']],flush=True)
