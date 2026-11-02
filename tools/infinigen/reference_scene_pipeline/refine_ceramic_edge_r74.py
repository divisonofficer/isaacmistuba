"""Controlled native bowl-edge fillet trial on6 standard WCs;2 compact contracts untouched."""
import bpy,json,hashlib
from pathlib import Path
root=Path('/jarvis/project/robomituba');base=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r73.blend';out=base/'scene_candidate_r74.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src))
def groups(mesh):
 adj=[set() for v in mesh.vertices]
 for e in mesh.edges:i,j=e.vertices;adj[i].add(j);adj[j].add(i)
 remaining=set(range(len(mesh.vertices)));result=[]
 while remaining:
  i=next(iter(remaining));group={i};queue=[i];remaining.remove(i)
  while queue:
   for j in adj[queue.pop()]:
    if j in remaining:remaining.remove(j);group.add(j);queue.append(j)
  result.append(group)
 return result

def other_signature(mesh,body):
 rows=[]
 for f in mesh.polygons:
  if all(i in body for i in f.vertices):continue
  rows.append((tuple(sorted(tuple(round(float(x),8) for x in mesh.vertices[i].co) for i in f.vertices)),f.material_index,f.use_smooth))
 return hashlib.sha256(repr(sorted(rows)).encode()).hexdigest()
standard=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('program_key','')).endswith('_wc') and o.get('wc_variant')!='native_concealed_cistern'];assert len(standard)==6;records=[]
for o in standard:
 o.data=o.data.copy();me=o.data;components=groups(me);body=max(components,key=len);assert len(body)==31064 and len(components)==9;before=other_signature(me,body);selected=[e.index for e in me.edges if e.use_edge_sharp and all(i in body for i in e.vertices)];assert len(selected)==1174;before_v=len(me.vertices);before_f=len(me.polygons);attr=me.attributes.get('bevel_weight_edge') or me.attributes.new('bevel_weight_edge','FLOAT','EDGE');attr.data.foreach_set('value',[1.0 if i in set(selected) else 0.0 for i in range(len(me.edges))]);bpy.context.view_layer.objects.active=o;bpy.ops.object.select_all(action='DESELECT');o.select_set(True);mod=o.modifiers.new('R74_native_ceramic_edge_fillet','BEVEL');mod.limit_method='WEIGHT';mod.width=.002;mod.segments=3;mod.harden_normals=True;mod.use_clamp_overlap=True;bpy.ops.object.modifier_apply(modifier=mod.name);me=o.data;after_components=groups(me);body_after=max(after_components,key=len);assert len(after_components)==9 and sorted(len(g) for g in after_components if g!=body_after)==sorted(len(g) for g in components if g!=body);assert other_signature(me,body_after)==before;assert len(me.vertices)>before_v and len(me.polygons)>before_f
 records.append({'object':o.name,'key':o['program_key'],'targeted_native_bowl_edges':len(selected),'nominal_local_bevel_offset_m':.002,'axis_scaled_nominal_offset_m':[abs(s)*.002 for s in o.scale],'segments':3,'clamp_overlap':True,'geometry_counts_before':[before_v,before_f],'geometry_counts_after':[len(me.vertices),len(me.polygons)],'nonbowl_geometry_material_smooth_signature_unchanged':before})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r74.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'records':records,'scope':'Only targeted bowl-edge bevels on6 standard WC meshes. Other connected components and2 compact WC objects unchanged;no material,roughness,light,layout orcamera edits.','hypothesis':'Native bowl faces already smooth;1174 sharp edges allrepresent>=30degree creases. Test real millimetre fillets rather thanblanket sharp-flag removal. Nominal offset canbe reduced byclamping;not a measured finalradius.','photorealism_accepted':False,'requires':'Saved6 preflights andsame-source/camera closeup pluswide comparison;reject ifbowl silhouette orrim shading regresses.'},indent=2));print('Saved candidate74 ceramic edge trial',len(records),flush=True)
