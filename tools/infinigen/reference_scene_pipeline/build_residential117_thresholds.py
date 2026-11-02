"""Build real finish-floor thresholds; remove two isolated floating1mm cubes, no promotion."""
import bpy,bmesh,json,hashlib,sys
from pathlib import Path
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import bounds
d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=base/'scene_candidate_r116_draft.blend';dst=base/'scene_candidate_r117_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src);bpy.ops.wm.open_mainfile(filepath=str(src));fz=bounds(bpy.data.objects['hallway_0/1.floor'])[1].z;build=json.loads((d/'core_wc104_planning/draft_build.json').read_text());rows=[]
for unit in [101,102]:
 floor=bpy.data.objects['hallway_0/1.floor' if unit==101 else 'hallway_0/4.floor'];mat=floor.data.materials[0];opening=next(x for x in build['relocated_entrances'] if x['unit']==unit)['opening_y_m'];cx=9 if unit==101 else 12.5;x0,x1=cx-.1165,cx+.1165;y0,y1=opening;z0=0;z1=fz;vv=[(x,y,z) for z in [z0,z1] for y in [y0,y1] for x in [x0,x1]];ff=[(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)];me=bpy.data.meshes.new('Continuous_threshold_floor_layer');me.from_pydata(vv,[],ff);me.materials.append(mat);bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);assert all(e.is_manifold for e in bm.edges);bm.to_mesh(me);bm.free();uv=me.uv_layers.new(name='UVMap')
 for p in me.polygons:
  for li in p.loop_indices:
   v=me.vertices[me.loops[li].vertex_index].co;uv.data[li].uv=(v.x,v.y)
 o=bpy.data.objects.new(f'Core117_entry_threshold_{unit}.floor',me);bpy.context.scene.collection.objects.link(o);o['program_key']=f'{unit}_entry_threshold117';o['audit_kind']='floor';be=o.modifiers.new('0.8mm finish arris','BEVEL');be.width=.0008;be.segments=3
 # Actual isolated cube remains in doorway after old material-based leaf articulation.
 door=next(o for o in bpy.context.scene.objects if o.get('program_key')==f'{unit}_core_wc_door');indices=set(range(1078,1086));assert len(door.data.vertices)>max(indices);coords=[door.data.vertices[i].co.copy() for i in indices];dims=[max(v[k] for v in coords)-min(v[k] for v in coords) for k in range(3)];assert max(dims)<.00101 and min(dims)>.00099
 links={i:set() for i in indices}
 for e in door.data.edges:
  a,b=e.vertices
  if a in indices:links[a].add(b)
  if b in indices:links[b].add(a)
 assert all(link<=indices for link in links.values());original_coordinates=[list(door.matrix_world@door.data.vertices[i].co) for i in sorted(indices)];door.data=door.data.copy();bm=bmesh.new();bm.from_mesh(door.data);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[bm.verts[i] for i in indices],context='VERTS');bm.to_mesh(door.data);bm.free();rows.append({'unit':unit,'threshold':o.name,'physical_floor_top_z_m':fz,'threshold_bounds_m':[[x0,y0,z0],[x1,y1,z1]],'material':mat.name,'floating_isolated_cube_removed':{'door':door.name,'vertices':8,'dimensions_m':dims,'world_vertices_before':original_coordinates},'route_correction':'Use measured entrance centre y6.75 instead of previous y6.8; test against full leaf/handles/casing.'})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==before;(d/'threshold117_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'candidate':str(dst),'candidate_sha256':sha(dst),'rows':rows,'scope':'Two genuine closed finish-floor bridge layers across previously unfilled doorway wall-width strips,0.8mm arris and existing floor material; two disconnected floating1mm cubes removed from native core door meshes. Native leaf/frame/handles otherwise unchanged. Actual floor and600mm route audits plus matched RGB required. Canonical room tags/import and full10-room navigation not accepted.','accepted':False},indent=2));print('RESIDENTIAL117_THRESHOLDS_SAVED')
