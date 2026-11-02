"""Open a single actual crew neckline and add a surface-following sewn band, not a painted decal."""
import bpy,bmesh,json,hashlib,math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r36.blend';out=base/'scene_candidate_r37.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));garments=[o for o in bpy.data.objects if '_native_garment_' in o.get('program_key','')];records=[]
def boundary_components(bm):
 pending={e for e in bm.edges if e.is_boundary};parts=[]
 while pending:
  edge=pending.pop();part={edge};stack=[edge]
  while stack:
   e=stack.pop()
   for v in e.verts:
    for other in v.link_edges:
     if other in pending:pending.remove(other);part.add(other);stack.append(other)
  parts.append(part)
 return parts
for o in garments:
 bm=bmesh.new();bm.from_mesh(o.data);remove=[];a=.102
 for f in bm.faces:
  c=f.calc_center_median()
  if abs(c.x)>=a:continue
  depth=.065 if c.y<0 else .035;threshold=-depth*math.sqrt(max(0,1-(c.x/a)**2))
  if c.z>threshold:remove.append(f)
 assert remove,o.name
 bmesh.ops.delete(bm,geom=remove,context='FACES');loose=[v for v in bm.verts if not v.link_faces]
 if loose:bmesh.ops.delete(bm,geom=loose,context='VERTS')
 necks=[]
 for part in boundary_components(bm):
  vertices={v for e in part for v in e.verts}
  if min(v.co.z for v in vertices)>-.13 and max(v.co.z for v in vertices)>-.08:necks.append(part)
 assert len(necks)==1,(o.name,'single neckline expected',len(necks))
 for v in {v for e in necks[0] for v in e.verts}:
  v.co.x=max(-a,min(a,v.co.x));depth=.065 if v.co.y<0 else .035;v.co.z=-depth*math.sqrt(max(0,1-(v.co.x/a)**2))
 bm.normal_update();bm.to_mesh(o.data);bm.free();o.data.update();records.append({'object':o.name,'removed_native_bridge_faces':len(remove),'raw_neck_boundary_components':1})
bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();materials={};contacts=[]
for o in garments:
 evaluated=o.evaluated_get(deps);mesh=evaluated.to_mesh();bm=bmesh.new();bm.from_mesh(mesh);necks=[]
 for part in boundary_components(bm):
  vertices={v for e in part for v in e.verts}
  if min(v.co.z for v in vertices)>-.13 and max(v.co.z for v in vertices)>-.08:necks.append(part)
 assert len(necks)==1,(o.name,'evaluated neckline',len(necks));part=necks[0];adj={}
 for e in part:
  for v in e.verts:adj.setdefault(v,[]).append(e.other_vert(v))
 assert all(len(neighbors)==2 for neighbors in adj.values()),o.name
 first=next(iter(adj));ordered=[first];prev=None;cur=first
 while True:
  nxt=next(v for v in adj[cur] if v!=prev)
  if nxt==first:break
  ordered.append(nxt);prev,cur=cur,nxt;assert len(ordered)<=len(adj)
 assert len(ordered)==len(adj)
 tree=BVHTree.FromPolygons([v.co.copy() for v in mesh.vertices],[list(f.vertices) for f in mesh.polygons]);positions=[];maximum=0;minimum_width=1
 for v in ordered:
  p=v.co.copy();depth=.065 if p.y<0 else .035;outward=Vector((p.x/(.102**2),0,p.z/(depth**2)))
  if outward.length<1e-9:outward=Vector((1,0,0))
  target=p+outward.normalized()*.012;hit,normal,idx,distance=tree.find_nearest(target);assert hit is not None and distance<.02,(o.name,distance)
  start,normal0,_,_=tree.find_nearest(p);A=start+normal0*.00035;B=hit+normal*.00035;positions.append((A,B));minimum_width=min(minimum_width,(B-A).length);maximum=max(maximum,tree.find_nearest(A)[3],tree.find_nearest(B)[3])
 assert maximum<.0015,(o.name,'band detached',maximum)
 n=len(positions);verts=[tuple(p[0]) for p in positions]+[tuple(p[1]) for p in positions];faces=[(k,(k+1)%n,n+(k+1)%n,n+k) for k in range(n)];data=bpy.data.meshes.new('Crewneck_sewn_band');data.from_pydata(verts,[],faces)
 original=o.data.materials[0]
 if original.name not in materials:
  mat=original.copy();mat.name='FineR37_ribbed_collar_'+original.name;bs=next(x for x in mat.node_tree.nodes if x.type=='BSDF_PRINCIPLED')
  if bs.inputs['Base Color'].is_linked:
   old=bs.inputs['Base Color'].links[0].from_socket;mix=mat.node_tree.nodes.new('ShaderNodeMixRGB');mix.blend_type='MULTIPLY';mix.inputs[0].default_value=1;mix.inputs[2].default_value=(.85,.85,.85,1);mat.node_tree.links.new(old,mix.inputs[1]);mat.node_tree.links.new(mix.outputs[0],bs.inputs['Base Color'])
  else:bs.inputs['Base Color'].default_value=tuple(c*.85 for c in bs.inputs['Base Color'].default_value[:3])+(1,)
  materials[original.name]=mat
 data.materials.append(materials[original.name])
 for f in data.polygons:f.use_smooth=True
 unit,_,_,tier,g=o['program_key'].split('_');band=bpy.data.objects.new(f'FineR37_{unit}_crewneck_{tier}_{g}',data);bpy.context.scene.collection.objects.link(band);band.parent=o;band['reference_scene_owner']='dual_unit_residential_floor_03';band['program_key']=f'{unit}_collar_band_{tier}_{g}';band['audit_kind']='detail';sol=band.modifiers.new('Sewn_band_thickness','SOLIDIFY');sol.thickness=.0006;sol.offset=0
 contacts.append({'garment':o.name,'loop_vertices':n,'maximum_band_to_evaluated_body_gap_m':maximum,'minimum_actual_band_width_m':minimum_width});bm.free();evaluated.to_mesh_clear()
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r37.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'trigger':'r36 boundary probe found two separate upper slits,not one readable crew neckline; loft alone did not cure flat shirt impression','changes':'actual asymmetric front/back crew neckline opening,removed native bridge,surface-following12mm nominal sewn band','garments':records,'band_contacts':contacts,'photorealism_accepted':False,'requires':'same-camera neckline/shoulder/torso comparison and frame/cloth regression'},indent=2));print('SAVED',out,flush=True)
