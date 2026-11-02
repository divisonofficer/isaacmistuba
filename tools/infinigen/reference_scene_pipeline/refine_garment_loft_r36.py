"""Rebuild native clothing with consistent neck/body proportions and varied actual patterns."""
import bpy,sys,json,math,hashlib,random
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'));sys.path.insert(0,str(ROOT/'modules/infinigen'));from room_planner import proc_assets as pa
base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';source=base/'scene_candidate_r35.blend';out=base/'scene_candidate_r36.blend';assert not out.exists();sha=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));protos=[];patterns=[]
for i in range(6):
 attrs={'width':[.40,.42,.39,.43,.41,.40][i],'size':[.51,.55,.50,.57,.53,.56][i],'size_neck':[.025,.032,.028,.030,.026,.035][i],'sleeve_width':.095 if i<4 else .105,'sleeve_length':.09 if i<4 else .23,'sleeve_angle':.60,'thickness':.022}
 o=pa._cloth('shirt','ShirtFactory',811330+i,**attrs);assert o is not None;o.rotation_euler=(math.pi/2,0,0);o.location=(i*2,0,0);protos.append(o);patterns.append(attrs);print('NATIVE_PATTERN',i,flush=True)
pa._drape(protos,pin_fn=lambda z,zmax:z>zmax-.035,frames=42)
removed=[]
for o in list(bpy.data.objects):
 if '_native_garment_' in o.get('program_key',''):removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
records=[]
for unit in (101,102):
 parent=next(o for o in bpy.data.objects if o.get('program_key')==str(unit)+'_dressing');rng=random.Random(unit+8300)
 for tier,railz in enumerate((1.8,1.05)):
  for g in range(6):
   idx=(g+2*tier+(unit-101)*3)%6;proto=protos[idx];o=proto.copy();o.data=proto.data.copy();bpy.context.scene.collection.objects.link(o);bounds=[(min(v.co[k] for v in o.data.vertices),max(v.co[k] for v in o.data.vertices)) for k in range(3)];factor=min(1,.47/(bounds[0][1]-bounds[0][0]),.59/(bounds[2][1]-bounds[2][0]));cx=sum(bounds[0])/2;cy=sum(bounds[1])/2;top=bounds[2][1]
   for v in o.data.vertices:v.co=Vector(((v.co.x-cx)*factor,(v.co.y-cy)*factor,(v.co.z-top)*factor))
   o.parent=parent;o.matrix_parent_inverse.identity();o.location=(.28,-1.005+g*.22,railz-.055);o.rotation_euler=(0,0,.90+rng.uniform(-.025,.025));o.scale=(1,1,1);o.name=f'FineR36_{unit}_native_shirt_{tier}_{g}';o.data.materials.clear();o.data.materials.append(bpy.data.materials['FineR1_garment_'+str((g+tier+unit)%5)]);o['reference_scene_owner']='dual_unit_residential_floor_03';o['program_key']=f'{unit}_native_garment_{tier}_{g}';o['audit_kind']='detail';o['infinigen_factory']='ShirtFactory';o['gravity_drape_frames']=42
   sub=o.modifiers.new('Soft_native_cloth_surface','SUBSURF');sub.levels=1;sub.render_levels=1
   # Fit actual rotated vertices to the unchanged closet frame gate.
   rot=__import__('mathutils').Matrix.Rotation(o.rotation_euler.z,4,'Z');points=[rot@v.co+o.location for v in o.data.vertices];lo=min(p.y for p in points);hi=max(p.y for p in points);delta=max(0,-1.19-lo) if lo< -1.20 else min(0,.29-hi) if hi>.30 else 0;o.location.y+=delta
   # Keep hanger orientation aligned with garment, preserving its supported hook/rail.
   hanger=next(x for x in bpy.data.objects if x.get('program_key')==f'{unit}_hanger_{tier}_{g}');angle=o.rotation_euler.z;yc=o.location.y;points=[]
   for x,z in [(-.18,railz-.13),(0,railz-.055),(.18,railz-.13),(-.18,railz-.13)]:points.append((.28+math.cos(angle)*x,yc+math.sin(angle)*x,z))
   for dst,co in zip(hanger.data.splines[0].points,points):dst.co=(*co,1)
   hook=next(x for x in bpy.data.objects if x.get('program_key')==f'{unit}_hook_{tier}_{g}');hook.location.y=o.location.y-hook.data.splines[0].points[0].co.y
   records.append({'object':o.name,'pattern_index':idx,'neck_parameter_m':patterns[idx]['size_neck'],'body_parameter_m':patterns[idx]['size'],'uniform_fit':factor})
for o in protos:bpy.data.objects.remove(o,do_unlink=True)
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r36.json').write_text(json.dumps({'source':str(source),'source_sha256':sha,'candidate':str(out),'reason':'r33/r34 still read flat. Source semantics: ShirtFactory thickness controls front/back SOLIDIFY separation before opening hems, not a final fabric membrane. Previous .0018-.002 override collapsed the garment loft versus native .02-.03 default.','change':'6 consistent native shirt patterns with .022m native loft, proportional neck/body,42-frame drape and actual rotated frame fit; no claim of22mm-thick cloth','patterns':patterns,'garments':records,'photorealism_accepted':False,'requires':'direct neckline/silhouette review;native name and cloth solver alone are not acceptance'},indent=2));print('SAVED',out,flush=True)
