"""Inferred upper exit within existing shaft: actual landing, wall aperture and native door."""
import bpy,bmesh,json,math,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';b=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=b/'scene_candidate_r113_draft.blend';dst=b/'scene_candidate_r114_draft.blend';assert not dst.exists();bpy.ops.wm.open_mainfile(filepath=str(src));floor=bpy.data.objects['bedroom_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box);mat=bpy.data.materials['Residential112_concrete_stair_structure'];plaster=bpy.data.materials['res03_plaster'];made=[]
def prism(name,x0,x1,profile,material):
 n=len(profile);me=bpy.data.meshes.new(name);me.from_pydata([(x,y,z) for x in [x0,x1] for y,z in profile],[],[tuple(reversed(range(n))),tuple(range(n,2*n))]+[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]);bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);assert all(e.is_manifold for e in bm.edges);bm.to_mesh(me);bm.free();o=bpy.data.objects.new(name,me);bpy.context.scene.collection.objects.link(o);o.data.materials.append(material);o['audit_kind']='stair_structure';o['program_key']=name;o['reference_scene_owner']='dual_unit_residential_floor_03';be=o.modifiers.new('2mm real arris','BEVEL');be.width=.002;be.segments=3;bpy.context.view_layer.objects.active=o;bpy.ops.object.modifier_apply(modifier=be.name);made.append(o);return o
bpy.data.objects.remove(bpy.data.objects['Residential112_concrete_upper'],do_unlink=True);y0=14.26;pitch=.24;end=y0-9*pitch;z0=fz+1.35;profile=[(y0,z0)]
for i in range(9):profile.extend([(y0-i*pitch,z0+(i+1)*.15),(y0-(i+1)*pitch,z0+(i+1)*.15)])
profile.extend([(end,z0+1.35-.18),(y0,z0-.18)]);prism('Residential114_concrete_upper',11.05,12.15,profile,mat)
mapy=lambda y:y0+(y-y0)*(.24/.29);moved=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or o.get('audit_kind')!='stair_guard' or 'landing_guard' in o.name:continue
 pts=[o.matrix_world@v.co for v in o.data.vertices];cx=(min(v.x for v in pts)+max(v.x for v in pts))/2
 if cx<10.75:continue
 if 'continuous_handrail' in o.name:
  lz=min(v.co.z for v in o.data.vertices);hz=max(v.co.z for v in o.data.vertices);aa=o.matrix_world@Vector((0,0,lz));bb=o.matrix_world@Vector((0,0,hz));length=(bb-aa).length;aa.y=mapy(aa.y);bb.y=mapy(bb.y);axis=bb-aa;o.location=(aa+bb)/2;o.rotation_euler=axis.to_track_quat('Z','Y').to_euler();o.scale.z*=(axis.length/length)
 else:o.location.y=mapy(o.location.y)
 moved.append(o.name)
level=fz+2.7;prism('Residential114_upper_landing',9.10,12.40,[(10.95,level),(end,level),(end,level-.18),(10.95,level-.18)],mat)
# Shaft closure with an actual unfilled1m door aperture.
cz=5.57
for name,x0,x1,zlo,zhi in [('left',9.04,11.10,level,cz),('right',12.10,12.46,level,cz),('lintel',11.10,12.10,level+2.34,cz)]:prism('Residential114_upper_exit_wall_'+name,x0,x1,[(11.0,zlo),(11.12,zlo),(11.12,zhi),(11.0,zhi)],plaster)
proto=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/native_flat_door_pilot02/asset.blend'
with bpy.data.libraries.load(str(proto),link=False) as (s,z):z.objects=['Office02_native_flat_leaf_full_frame_lever']
door=z.objects[0];bpy.context.scene.collection.objects.link(door);door.name='Residential114_upper_exit_native_door';door.matrix_world=Matrix.Translation(Vector((11.6,11.06,level)));door['program_key']='upper_exit_native_door';door['native_source_asset']=str(proto);door['audit_kind']='architecture';bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();rays=[]
for x in [11.2,11.6,12.0]:
 for y in [11.3,11.6,11.9]:
  hit,pt,n,i,o,m=bpy.context.scene.ray_cast(deps,Vector((x,y,level+.01)),Vector((0,0,1)),distance=6);gap=pt.z-level if hit else None;rays.append({'x':x,'y':y,'clearance_m':gap,'hit':o.name if hit else None,'pass':gap is None or gap>=2})
assert all(x['pass'] for x in rays),rays
bpy.ops.wm.save_as_mainfile(filepath=str(dst));(d/'stair114_upper_connection.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'candidate':str(dst),'candidate_sha256':hashlib.sha256(dst.read_bytes()).hexdigest(),'new_upper_going_m':pitch,'rise_m':.15,'upper_landing_depth_m':end-11.0,'exit_native_door_source':str(proto),'new_structure':[o.name for o in made],'upper_guards_repositioned':moved,'upper_landing_headroom_samples':rays,'accepted':False,'scope':'Inferred next-floor exit within shaft, not supplied upper-floor reference reconstruction. Closed native slab door at actual wall aperture and supported landing; no fire rating/regulatory certification, full door swing/nav or visual acceptance. Lower tread geometry and nightstand trial unaffected (source113 branch108).'},indent=2));print('STAIR114_UPPER_CONNECTION_SAVED')
