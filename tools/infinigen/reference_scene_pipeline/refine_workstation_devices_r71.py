"""Resolve existing24 monitor identities,add bounded supported input devices; no duplicate monitors/layout/light changes."""
import bpy,bmesh,json,hashlib,math,random
from pathlib import Path
from mathutils import Matrix
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r70.blend';out=base/'scene_candidate_r71.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rng=random.Random(48712571)
def mat(name,color,rough):
 m=bpy.data.materials.new(name);m.use_nodes=True;bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(*color,1);bs.inputs['Roughness'].default_value=rough;return m
body=mat('DeviceR71_molded_charcoal',(.018,.021,.024),.48);glass=mat('DeviceR71_off_display_glass',(.008,.012,.017),.17);key=mat('DeviceR71_keycap',(.045,.048,.052),.42);metal=mat('DeviceR71_stand',(.08,.09,.10),.32);metal.node_tree.nodes.get('Principled BSDF').inputs['Metallic'].default_value=.8
def make(name,boxes,materials,parent):
 vs=[];fs=[];mi=[]
 for c,d,m in boxes:
  offset=len(vs);vs.extend([(c[0]+a*d[0]/2,c[1]+b*d[1]/2,c[2]+z*d[2]/2) for a,b,z in [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]]);fs.extend([tuple(offset+i for i in face) for face in [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]]);mi.extend([m]*6)
 me=bpy.data.meshes.new(name);me.from_pydata(vs,[],fs)
 for m in materials:me.materials.append(m)
 for f,i in zip(me.polygons,mi):f.material_index=i
 o=bpy.data.objects.new(name,me);bpy.context.collection.objects.link(o);o.parent=parent;o.matrix_parent_inverse=Matrix.Identity(4);o.matrix_basis=Matrix.Identity(4);o['program_key']=parent['program_key']+'_device_detail_'+name;o['audit_kind']='detail';be=o.modifiers.new('Product edge radius','BEVEL');be.width=.0007;be.segments=3;return o
records=[]
for o in [x for x in bpy.data.objects if x.type=='MESH' and 'DeskBenchFactory' in x.name]:
 adj={v.index:set() for v in o.data.vertices}
 for e in o.data.edges:a,b=e.vertices;adj[a].add(b);adj[b].add(a)
 unseen=set(adj);screens=[];standids=set()
 while unseen:
  todo=[unseen.pop()];ids=set(todo)
  while todo:
   for i in adj[todo.pop()]:
    if i in unseen:unseen.remove(i);ids.add(i);todo.append(i)
  vs=[o.data.vertices[i].co for i in ids];lo=[min(v[k] for v in vs) for k in range(3)];hi=[max(v[k] for v in vs) for k in range(3)];dims=[hi[k]-lo[k] for k in range(3)]
  if len(ids)==8 and abs(dims[0]-.02)<1e-4 and abs(dims[1]-.56)<1e-4 and abs(dims[2]-.34)<1e-4:screens.append((ids,[(lo[k]+hi[k])/2 for k in range(3)]))
  if len(ids)==8 and abs(dims[0]-.03)<1e-4 and abs(dims[1]-.04)<1e-4 and abs(dims[2]-.2)<1e-4:standids.update(ids)
 assert len(screens)==4 and len(standids)==32,(o.name,len(screens),len(standids));idx=len(o.data.materials);o.data.materials.append(body);o.data.materials.append(metal);screenids=set().union(*(x[0] for x in screens))
 for face in o.data.polygons:
  if face.vertices[0] in screenids:face.material_index=idx
  elif face.vertices[0] in standids:face.material_index=idx+1
 for j,(ids,c) in enumerate(screens):
  side=1 if c[0]>0 else -1;name=o['program_key']+'_'+str(j);make('Display_'+name,[((side*.3505,c[1],1.005),(.0008,.535,.306),0)],[glass],o);make('Base_'+name,[((side*.34,c[1],.752),(.16,.22,.004),0)],[metal],o)
  # Keyboard actual body/caps; outer table edge isabsX.83,seat halfwidth.595.
  cx=side*.65;cy=c[1]-.045;boxes=[((cx,cy,.7565),(.135,.35,.012),0)]
  for row in range(4):
   for col in range(14):boxes.append(((cx+side*(row-1.5)*.026,cy+(col-6.5)*.0238,.7645),(.020,.020,.004),1))
  boxes.append(((cx+side*.056,cy,.7645),(.018,.13,.004),1));kb=make('Keyboard_'+name,boxes,[body,key],o);assert max(abs(v.co.x) for v in kb.data.vertices)<.83;assert min(v.co.z for v in kb.data.vertices)>.75
  # Curved mouse,single optical wheel; both remain in the same desk footprint.
  bpy.ops.mesh.primitive_uv_sphere_add(segments=24,ring_count=12);mouse=bpy.context.object;mouse.name='Mouse_'+name;mouse.parent=o;mouse.matrix_parent_inverse=Matrix.Identity(4);mouse.location=(side*.65,c[1]+.24,.765);mouse.scale=(.047,.030,.0145);mouse.data.materials.append(body)
  for f in mouse.data.polygons:f.use_smooth=True
  mouse['program_key']=name+'_mouse';mouse['audit_kind']='detail';make('MouseWheel_'+name,[((side*.67,c[1]+.24,.779),(.014,.006,.004),0)],[key],o)
  records.append({'pod':o.name,'existing_screen_center_local':c,'native_monitor_reused':True,'keyboard_bottom_gap_m':.0005,'keyboard_inside_native_top':True,'monitor_material_change':'native screen housing and stand face subsets only;shared ir_black_metal elsewhere untouched','note':'Input device footprint/support preflight only;visual and whole-scene regression pending.'})
assert len(records)==24;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r71.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'trigger':'Full16 review cannot identify open-workplace monitors. Source probe shows24 native screen boxes/stands withshared scanned normal shader,no front display glass or input devices.','changes':records,'photorealism_accepted':False,'requires':'Saved-source audits,same-camera broad views andmanufacturing closeup,no dataset promotion'},indent=2));print('Saved',out,flush=True)
