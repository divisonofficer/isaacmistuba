"""Continuous round rear leg/stile with arclength wood UV, replacing angular added blades."""
import bpy,bmesh,math,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r45.blend';out=base/'scene_candidate_r46.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
def tree(o):return BVHTree.FromPolygons([v.co.copy() for v in o.data.vertices],[list(f.vertices) for f in o.data.polygons])
for parent in list(bpy.data.objects):
 key=parent.get('program_key','')
 if parent.type!='MESH' or not key.startswith('breakout_chair') or parent.parent is not None:continue
 mat=next(m for m in parent.data.materials if m and 'oak' in m.name)
 for o in list(parent.children):
  if '_rear_stile_' in o.get('program_key',''):bpy.data.objects.remove(o,do_unlink=True)
 parent.data=parent.data.copy();bm=bmesh.new();bm.from_mesh(parent.data);remove=[v for v in bm.verts if v.co.x<0];assert remove and len(remove)<len(bm.verts);removed=len(remove);bmesh.ops.delete(bm,geom=remove,context='VERTS');bm.to_mesh(parent.data);bm.free();parent.data.update()
 back=next(o for o in parent.children if o.get('program_key')==key+'_back_upholstery');backtree=tree(back);apron=next(o for o in parent.children if o.get('program_key')==key+'_rear_apron');aprontree=tree(apron);uv=apron.data.uv_layers.get('UVMap') or apron.data.uv_layers.new(name='UVMap')
 for f in apron.data.polygons:
  for li in f.loop_indices:
   q=apron.data.vertices[apron.data.loops[li].vertex_index].co;uv.data[li].uv=(q.z*2,q.y*2)
 supports=[]
 for side,sign in enumerate([-1,1]):
  rings=49;segments=32;centers=[]
  for j in range(rings):
   z=.68*j/(rings-1);t=max(0,min(1,(z-.38)/.27));s=t*t*(3-2*t);centers.append(Vector((-.20,sign*(.20-.055*s),z)))
  verts=[];lengths=[0.0]
  for j,C in enumerate(centers):
   if j:lengths.append(lengths[-1]+(C-centers[j-1]).length)
   tangent=(centers[min(j+1,rings-1)]-centers[max(j-1,0)]).normalized();U=Vector((1,0,0));V=tangent.cross(U).normalized();r=.016-.002*min(1,C.z/.38)+.002*max(0,(C.z-.38)/.30)
   for k in range(segments):verts.append(C+r*(math.cos(k*math.tau/segments)*U+math.sin(k*math.tau/segments)*V))
  faces=[tuple(reversed(range(segments)))];faceuv=[[(k/segments,0) for k in reversed(range(segments))]]
  for j in range(rings-1):
   for k in range(segments):
    kn=(k+1)%segments;faces.append((j*segments+k,j*segments+kn,(j+1)*segments+kn,(j+1)*segments+k));faceuv.append([(k/segments,lengths[j]),((k+1)/segments,lengths[j]),((k+1)/segments,lengths[j+1]),(k/segments,lengths[j+1])])
  faces.append(tuple((rings-1)*segments+k for k in range(segments)));faceuv.append([(k/segments,lengths[-1]) for k in range(segments)]);mesh=bpy.data.meshes.new('Continuous_rear_leg_stile');mesh.from_pydata(verts,[],faces);mesh.materials.append(mat);uv=mesh.uv_layers.new(name='UVMap')
  for f,values in zip(mesh.polygons,faceuv):
   f.use_smooth=len(f.vertices)==4
   for li,p in zip(f.loop_indices,values):uv.data[li].uv=p
  o=bpy.data.objects.new('BreakoutR46_continuous_rear_leg',mesh);bpy.context.scene.collection.objects.link(o);o.parent=parent;o['program_key']=key+f'_continuous_rear_stile_{side}';o['reference_scene_owner']='commercial_office_floor_02';o['audit_kind']='detail';mod=o.modifiers.new('Rounded end edges','BEVEL');mod.width=.001;mod.segments=3;mod.limit_method='ANGLE';t=tree(o);contact={'back_surface_pairs':len(t.overlap(backtree)),'apron_surface_pairs':len(t.overlap(aprontree))};assert all(v>0 for v in contact.values()),contact;floor=min(v.co.z for v in mesh.vertices);assert abs(floor)<1e-6;supports.append({'object':o.name,'continuous_floor_to_back':True,'floor_minimum_z_m':floor,'section_diameter_m':[.028,.032],'rings':rings,'circumference_segments':segments,'uv':'circumference U / arclength V','surface_contacts':contact})
 rows.append({'chair':key,'removed_old_rear_leg_vertices':removed,'new_rear_members':supports,'front_legs_and_upholstery':'unchanged'})
assert len(rows)==4;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r46.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'changes':rows,'scope':'continuous rear support geometry andlengthwise timber UV only;camera,lighting,textile unchanged','trigger':'Fresh45 review:angular blade,abrupt round-leg joint,weak timber grain','photorealism_accepted':False,'requires':'same front/rear cameras andscoped physical regression,independent review'},indent=2));print('SAVED',out,flush=True)
