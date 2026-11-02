"""Actual native compact media, reference-facing seating and physical privacy returns; unapproved trial."""
import bpy,bmesh,json,hashlib,sys,math,statistics
from pathlib import Path
from mathutils import Vector,Matrix
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from compact_wc_contract import mesh_geometry_hash
from curated_gltf_materials import preserve_native_packed_image
base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r126_draft.blend';dst=base/'scene_candidate_r127_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();source_sha=sha(src);studio=d/'native_media_products/review_studio_roles_v2.blend';scope=json.loads((d/'native_media_products/scope.json').read_text());assert sha(studio)==scope['source_sha256'];assert (d/'native_media_products/independent_coverage_verified.json').exists();bpy.ops.wm.open_mainfile(filepath=str(src));scene=bpy.context.scene;fz=.1145347;removed=[];rows=[];architecture=[];oldmatrices={o.name:[list(v) for v in o.matrix_world] for o in scene.objects}
def bounds(objects):
 ps=[o.matrix_world@v.co for o in objects for v in o.data.vertices];return Vector([min(p[k] for p in ps) for k in range(3)]),Vector([max(p[k] for p in ps) for k in range(3)])
def remove(o,reason):
 removed.append({'object':o.name,'program_key':o.get('program_key'),'reason':reason,'polygons':len(o.data.polygons) if o.type=='MESH' else None});bpy.data.objects.remove(o,do_unlink=True)
for unit in [101,102]:
 o=next(o for o in scene.objects if o.get('program_key')==f'{unit}_living_media')
 for part in [o]+list(o.children_recursive):remove(part,'Side-facing overwide media assembly from125/126 replaced by actual native compact product family. Its mesh LEDs are removed with it; transport lights/world/exposure not edited.')
for i in [0,3]:
 for kind in ['plant','pot','soil']:remove(bpy.data.objects[f'Residential03_r14_{kind}_{i}'],'Entire old sparse potted set removed from corridor/console zone; actual native ficus retained/reused, not merely excluded from physics.')
def mesh_object(name,vs,fs,material,key):
 me=bpy.data.meshes.new(name);me.from_pydata(vs,[],fs);me.update();bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(me);bm.free();o=bpy.data.objects.new(name,me);scene.collection.objects.link(o);me.materials.append(material);o['program_key']=key;o['reference_scene_owner']='dual_unit_residential_floor_03';o['audit_kind']='architecture';o['architecture_added127']=True;be=o.modifiers.new('Actual plaster edge arris1_5mm','BEVEL');be.width=.0015;be.segments=3;return o
# Fill only the upper portion of the open living/hall edge. Native room finish planes define thickness.
for unit,rid in [(101,'living-room_0/0'),(102,'living-room_0/1')]:
 wall=bpy.data.objects[rid+'.wall'];cz=min((bpy.data.objects[rid+'.ceiling'].matrix_world@Vector(v)).z for v in bpy.data.objects[rid+'.ceiling'].bound_box);mat=wall.data.materials[0];x0,x1=(6.8854653,7.1145347) if unit==101 else (14.3854653,14.6145347);y0,y1=7.55,9.3854653;vs=[(x,y,z) for z in [fz,cz] for y in [y0,y1] for x in [x0,x1]];fs=[(0,2,3,1),(4,5,7,6),(0,1,5,4),(2,6,7,3),(0,4,6,2),(1,3,7,5)];o=mesh_object(f'Residential127_{unit}_living_media_privacy_return',vs,fs,mat,f'{unit}_living_media_privacy_return');architecture.append({'object':o.name,'bounds_m':[[x0,y0,fz],[x1,y1,cz]],'thickness_m':x1-x0,'living_entry_opening_y_retained_m':[6.5145445,y0],'kind':'Authored fixed real wall, reference-derived/inferred reconstruction, not a native product or physics proxy.'})
 # A real extruded painted trim profile, not a low box used in place of furniture.
 side=x0 if unit==101 else x1;sign=-1 if unit==101 else 1;profile=[(0,0),(.012,0),(.012,.055),(.010,.067),(.007,.07),(0,.07)];verts=[(side+sign*x,y,fz+z) for y in [y0,y1] for x,z in profile];n=len(profile);faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]+[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)];trim_mat=bpy.data.objects['skirtingboard_support'].data.materials[0];trim=mesh_object(f'Residential127_{unit}_privacy_return_trim',verts,faces,trim_mat,f'{unit}_privacy_return_trim');architecture[-1]['painted_trim_object']=trim.name
# Rigidly return101 ficus to its earlier screened floor location; add a rotated native twin in102.
plant=bpy.data.objects['Residential03_r89_native_ficus_101_living'];native_plant_hash=mesh_geometry_hash(plant.data);lo,hi=bounds([plant]);delta=Vector((2.65-(lo.x+hi.x)/2,9.0-(lo.y+hi.y)/2,0));plant.matrix_world=Matrix.Translation(delta)@plant.matrix_world;lo,hi=bounds([plant]);twin=plant.copy();scene.collection.objects.link(twin);twin.name='Residential127_102_native_ficus';centre=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));twin.matrix_world=Matrix.Translation(Vector((18.85,9.,lo.z)))@Matrix.Rotation(math.pi,4,'Z')@Matrix.Translation(-centre)@plant.matrix_world;twin['program_key']='102_living_real_ficus';assert mesh_geometry_hash(twin.data)==native_plant_hash
plants={'101':{'object':plant.name,'rigid_translation_m':list(delta),'geometry_sha256':native_plant_hash},'102':{'object':twin.name,'rigid_rotation_z_deg':180,'geometry_sha256':native_plant_hash}}
wood_root=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/pbr_assets/polyhaven_oak_veneer_03';prov=json.loads((wood_root/'provenance.json').read_text())
for f in prov['files']:assert sha(r/f['path'])==f['sha256']
wood_change=None
for unit in [101,102]:
 for kind,assetid in [('console','HSSD_82853146797ce9b1ec5fa02d085f6cf816c243f5'),('tv','HSSD_f359e92c249c96d0121f40252c856f99008f9c2e')]:
  e=next(x for x in scope['assets'] if x['id']==assetid);names=list(e['objects'])
  with bpy.data.libraries.load(str(studio),link=False) as (available,loaded):loaded.objects=list(names)
  objs=loaded.objects;assert len(objs)==3 and all(o and o.type=='MESH' for o in objs);expected={}
  for o in objs:scene.collection.objects.link(o)
  bpy.context.view_layer.update() # Evaluate native imported transforms before reading matrix_world.
  for i,(name,o) in enumerate(zip(names,objs)):
   expected[o.name]=e['native_geometry_sha256'][name];assert mesh_geometry_hash(o.data)==expected[o.name];M=o.matrix_world.copy();o.parent=None;o.matrix_world=M;o.name=f'Residential127_{unit}_{kind}_native_{i}';o['original_asset_id']=assetid;o['program_key']=f'{unit}_living_{kind}' if i==0 else f'{unit}_living_{kind}_part{i}';o['audit_kind']='furniture';o['reference_scene_owner']='dual_unit_residential_floor_03';o['native_geometry_sha256']=e['native_geometry_sha256'][name]
  rotation=Matrix.Rotation((-1 if unit==101 else 1)*math.pi/2,4,'Z')
  for o in objs:o.matrix_world=rotation@o.matrix_world
  bpy.context.view_layer.update();lo,hi=bounds(objs);sz=hi-lo;native=e['actual_dimensions_xyz_m'];assert max(abs(sz[i]-native[j]) for i,j in [(0,1),(1,0),(2,2)])<1e-5,(assetid,list(sz),native)
  lo,hi=bounds(objs);desired_back=(6.86 if kind=='console' else 6.8849653) if unit==101 else (14.64 if kind=='console' else 14.6150347);delta=Vector((desired_back-(hi.x if unit==101 else lo.x),8.45-(lo.y+hi.y)/2,(fz if kind=='console' else .95)-lo.z))
  for o in objs:o.matrix_world=Matrix.Translation(delta)@o.matrix_world
  lo,hi=bounds(objs);assert hi.y<9.3855 and lo.y>7.55;assert all(mesh_geometry_hash(o.data)==o['native_geometry_sha256'] for o in objs)
  if unit==101 and kind=='console':
   originals={m for o in objs for m in o.data.materials if m and m.name.startswith('HSSD_MAT::82853146797ce9b1ec5fa02d085f6cf816c243f5::000')};assert len(originals)==1;old=next(iter(originals));mat=old.copy();mat.name='Residential127_101_photographic_oak_finish';ratios=[]
   for o in objs:
    me=o.data;uv=me.uv_layers.active;assert uv;me.calc_loop_triangles()
    for t in me.loop_triangles:
     if me.materials[me.polygons[t.polygon_index].material_index] not in originals:continue
     pp=[o.matrix_world@me.vertices[j].co for j in t.vertices];tt=[uv.data[j].uv.copy() for j in t.loops];area=(pp[1]-pp[0]).cross(pp[2]-pp[0]).length*.5;ua=abs((tt[1].x-tt[0].x)*(tt[2].y-tt[0].y)-(tt[1].y-tt[0].y)*(tt[2].x-tt[0].x))*.5
     if area>1e-4 and ua>1e-8:ratios.append((math.sqrt(area/ua),area))
   assert ratios;ratios.sort();total=sum(w for v,w in ratios);acc=0;scale=1
   for v,w in ratios:
    acc+=w
    if acc>=total/2:scale=v;break
   assert .05<scale<20;nodes=mat.node_tree.nodes;links=mat.node_tree.links;bs=next(n for n in nodes if n.type=='BSDF_PRINCIPLED');tc=nodes.new('ShaderNodeTexCoord');mapping=nodes.new('ShaderNodeVectorMath');mapping.operation='SCALE';mapping.inputs[3].default_value=scale;links.new(tc.outputs['UV'],mapping.inputs[0]);textures={}
   for role,suffix,color in [('color','diff_4k.jpg',True),('roughness','rough_4k.jpg',False),('normal','nor_gl_4k.png',False)]:
    im=bpy.data.images.load(str(wood_root/('oak_veneer_03_'+suffix)),check_existing=True);im.colorspace_settings.name='sRGB' if color else 'Non-Color';tx=nodes.new('ShaderNodeTexImage');tx.image=im;tx.extension='REPEAT';links.new(mapping.outputs[0],tx.inputs['Vector']);textures[role]=tx
   for name in ['Base Color','Roughness','Normal']:
    for link in list(bs.inputs[name].links):links.remove(link)
   links.new(textures['color'].outputs['Color'],bs.inputs['Base Color']);links.new(textures['roughness'].outputs['Color'],bs.inputs['Roughness']);normal=nodes.new('ShaderNodeNormalMap');normal.space='TANGENT';normal.inputs['Strength'].default_value=1;links.new(textures['normal'].outputs['Color'],normal.inputs['Color']);links.new(normal.outputs['Normal'],bs.inputs['Normal']);bs.inputs['Metallic'].default_value=0;bs.inputs['IOR'].default_value=1.5;bs.inputs['Coat Weight'].default_value=.2;bs.inputs['Coat Roughness'].default_value=.2;bs.inputs['Transmission Weight'].default_value=0
   for o in objs:
    o.data=o.data.copy()
    for i,m in enumerate(o.data.materials):
     if m in originals:o.data.materials[i]=mat
   wood_change={'material':mat.name,'replaces_native_finish_only':old.name,'source_provenance':str(wood_root/'provenance.json'),'source_files':prov['files'],'native_uv_unchanged':True,'mapping':'Native UV multiplied by area-weighted median metres_per_UV over real large wood triangles, referenced to1m photographic texture. Not exact per-panel texel-density calibration.','uv_multiplier':scale,'coat_weight':.2,'coat_roughness':.2,'normal_space':'TANGENT','method':'Photographic PBR, not measuredBRDF/scanner-certified; no added noise, hue tint or exposure edits.'}
  rows.append({'unit':unit,'kind':kind,'asset_id':assetid,'objects':[o.name for o in objs],'world_bbox_m':[list(lo),list(hi)],'native_polygons':sum(len(o.data.polygons) for o in objs),'native_mesh_identity_unchanged':all(mesh_geometry_hash(o.data)==o['native_geometry_sha256'] for o in objs),'post_import_rescaling':False,'orientation_z_deg':-90 if unit==101 else 90,'support_plan':'Real floor contacts for console; fixed wall back-interface0.5mm nominal for TV. Must be reopened/ray checked; no invisible stand proxy.'})
images={n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image};packed=[preserve_native_packed_image(im) for im in images];bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==source_sha;(d/'compact_media127_build.json').write_text(json.dumps({'source':str(src),'source_sha256':source_sha,'candidate':str(dst),'candidate_sha256':sha(dst),'native_studio':str(studio),'native_studio_sha256':sha(studio),'removed':removed,'architecture':architecture,'plants':plants,'products':rows,'wood_finish_variant101':wood_change,'packed_images':packed,'accepted':False,'scope':'Compact actual native products at original dimensions face primary seating, with real authored privacy returns and entry opening retained.101 photographic oak finish vs102 original dark finish. Not a shader-only/lighting-isolation experiment: old mesh LED strips removed with furniture, geometry/shadows change; world/transport light/exposure settings untouched. Source126 fixes retained. Full physical routes/floor/support/intersections, reference sightlines and matched RGB/independent review still required; no promotion.'},indent=2));print('RESIDENTIAL127_COMPACT_NATIVE_MEDIA_SAVED',[(x['unit'],x['kind'],x['world_bbox_m']) for x in rows],wood_change['uv_multiplier'])
