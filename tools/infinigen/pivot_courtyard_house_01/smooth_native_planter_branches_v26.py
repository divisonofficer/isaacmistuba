"""Smooth native branch chains before accepting the entry vegetation silhouette."""
import bpy,json,math,collections
from pathlib import Path
from mathutils import Vector,Matrix
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';rows=[]
m=bpy.data.materials.new('entry_v26_fine_matte_bark');m.use_nodes=True;nt=m.node_tree;bs=nt.nodes['Principled BSDF'];bs.inputs['Roughness'].default_value=.82;tc=nt.nodes.new('ShaderNodeTexCoord');noise=nt.nodes.new('ShaderNodeTexNoise');noise.inputs['Scale'].default_value=15;noise.inputs['Detail'].default_value=2;nt.links.new(tc.outputs['Object'],noise.inputs['Vector']);ramp=nt.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(.095,.07,.035,1);ramp.color_ramp.elements[1].color=(.18,.14,.08,1);nt.links.new(noise.outputs['Fac'],ramp.inputs[0]);nt.links.new(ramp.outputs['Color'],bs.inputs['Base Color']);bump=nt.nodes.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.10;bump.inputs['Distance'].default_value=.001;nt.links.new(noise.outputs['Fac'],bump.inputs['Height']);nt.links.new(bump.outputs['Normal'],bs.inputs['Normal'])
for i in range(2):
 root=bpy.data.objects['PivotLeafyV9_planter_'+str(i)];sk=next(o for o in root.children_recursive if o.type=='MESH' and len(o.data.vertices)<500 and len(o.data.edges)>0);T=root.matrix_world.inverted()@sk.matrix_world;points=[T@v.co for v in sk.data.vertices];adj={j:[] for j in range(len(points))}
 for edge in sk.data.edges:
  a,b=edge.vertices;adj[a].append(b);adj[b].append(a)
 visited=set();chains=[]
 def walk(a,b):
  chain=[a,b];visited.add(tuple(sorted((a,b))));prev,cur=a,b
  while len(adj[cur])==2:
   nxt=next((v for v in adj[cur] if v!=prev),None)
   if nxt is None or tuple(sorted((cur,nxt))) in visited:break
   visited.add(tuple(sorted((cur,nxt))));chain.append(nxt);prev,cur=cur,nxt
  return chain
 for a,neighbors in adj.items():
  if len(neighbors)!=2:
   for b in neighbors:
    if tuple(sorted((a,b))) not in visited:chains.append(walk(a,b))
 for edge in sk.data.edges:
  a,b=edge.vertices
  if tuple(sorted((a,b))) not in visited:chains.append(walk(a,b))
 assert len(visited)==len(sk.data.edges),(len(visited),len(sk.data.edges))
 lo=min(p.z for p in points);hi=max(p.z for p in points);radius=[max(.14,1-.82*(p.z-lo)/(hi-lo)) for p in points]
 attrs=[a for a in sk.data.attributes if 'radius' in a.name.lower() and a.domain=='POINT' and a.data_type=='FLOAT'];radius_source='monotonic height taper'
 if attrs:
  values=[v.value for v in attrs[0].data]
  if max(values)>0:radius=[max(.12,min(1,v/max(values))) for v in values];radius_source=attrs[0].name
 curve=bpy.data.curves.new('native_planter_smooth_branch_chains','CURVE');curve.dimensions='3D';curve.bevel_depth=.012/root.matrix_world.to_scale().x;curve.bevel_resolution=4;curve.resolution_u=12;curve.use_fill_caps=True
 for chain in chains:
  sp=curve.splines.new('BEZIER');sp.bezier_points.add(len(chain)-1)
  for p,index in zip(sp.bezier_points,chain):p.co=points[index];p.handle_left_type='AUTO';p.handle_right_type='AUTO';p.radius=radius[index]
 old=bpy.data.objects['PivotEntryV25_native_tapered_branches_'+str(i)];bpy.data.objects.remove(old,do_unlink=True);o=bpy.data.objects.new('PivotEntryV26_smooth_native_branches_'+str(i),curve);bpy.context.scene.collection.objects.link(o);o.parent=root;o.matrix_basis=Matrix.Identity(4);curve.materials.append(m);o['ir_room']='entry_deck';rows.append({'planter':i,'native_edges':len(visited),'smooth_chains':len(chains),'radius_source':radius_source,'base_radius_world_m':.012,'native_canopy_preserved':True})
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='quality_rework_v26';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v26.blend'));(B/'entry_branch_smoothing_v26.json').write_text(json.dumps({'status':'entry_only_visual_gate_pending','reason':'V25 corrected inverse taper but straight skeleton segments still produced visible wire-like elbows. Connected Bezier chains preserve native joints and foliage while smoothing the stems.','changes':rows,'next':'Direct original-camera visual inspection before launching full regression'},indent=2)+'\n');print('PIVOT_ENTRY_BRANCHES_V26_SAVED',rows,flush=True)
