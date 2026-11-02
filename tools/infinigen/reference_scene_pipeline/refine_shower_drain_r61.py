"""Replace eight solid shower tray blocks with recessed sloped trays and actual open-slot grates. No shader/light/camera changes."""
import bpy,bmesh,json,hashlib
from pathlib import Path
from mathutils import Matrix
r=Path('/jarvis/project/robomituba');ref=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=base/'scene_candidate_r60.blend';out=base/'scene_candidate_r61.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));records=[]
def make(name,verts,faces,mat,parent):
 me=bpy.data.meshes.new(name);me.from_pydata(verts,[],faces);me.materials.append(mat);me.update();o=bpy.data.objects.new(name,me);bpy.context.collection.objects.link(o);o.parent=parent;o.matrix_parent_inverse=Matrix.Identity(4);o.matrix_basis=Matrix.Identity(4);o['program_key']=parent['program_key']+'_'+name;o['support_object']=parent.name;return o
def box(name,c,d,mat,parent):
 vs=[(c[0]+a*d[0]/2,c[1]+b*d[1]/2,c[2]+z*d[2]/2) for a,b,z in [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]];fs=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)];return make(name,vs,fs,mat,parent)
metal=bpy.data.materials.new('DrainR61_stainless');metal.use_nodes=True;bs=metal.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.48,.50,.52,1);bs.inputs['Metallic'].default_value=1;bs.inputs['Roughness'].default_value=.27
dark=bpy.data.materials.new('DrainR61_cavity');dark.use_nodes=True;bs=dark.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.012,.014,.015,1);bs.inputs['Roughness'].default_value=.7
showers=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('program_key','')).endswith('_shower')];assert len(showers)==8
for o in showers:
 ids=[v.index for v in o.data.vertices if v.co.z<.081];assert len(ids)==8,(o.name,len(ids));traymat=next(m for m in o.data.materials if m and m.name=='ir_shower_tray');bm=bmesh.new();bm.from_mesh(o.data);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[bm.verts[i] for i in ids],context='VERTS');bm.to_mesh(o.data);bm.free();o.data.update()
 rings=[(.475,0),(.475,.08),(.45,.08),(.44,.065),(.055,.042),(.05,.040),(.05,0)];vs=[]
 for a,z in rings:vs.extend([(-a,-a,z),(a,-a,z),(a,a,z),(-a,a,z)])
 fs=[]
 for j in range(len(rings)-1):
  for k in range(4):n=(k+1)%4;fs.append((j*4+k,j*4+n,(j+1)*4+n,(j+1)*4+k))
 for k in range(4):n=(k+1)%4;fs.append((24+k,24+n,n,k))
 tray=make('RecessedTray_'+o['program_key'],vs,fs,traymat,o);bevel=tray.modifiers.new('Molded edge radius','BEVEL');bevel.width=.0007;bevel.segments=3
 for axis in range(2):
  for sign in [-1,1]:
   c=[0,0,.042];c[axis]=sign*.047;d=[.096,.096,.002];d[axis]=.004;box('DrainFrame_'+str(axis)+'_'+str(sign)+'_'+o['program_key'],c,d,metal,o)
 for i in range(13):box('DrainBar_'+str(i)+'_'+o['program_key'],(-.041+i*.0068,0,.042),(.0028,.090,.002),metal,o)
 box('DrainWell_'+o['program_key'],(0,0,.014),(.098,.098,.002),dark,o)
 records.append({'shower':o.name,'removed_solid_tray_vertices':8,'tray_outer_width_m':.95,'rim_height_m':.08,'floor_edge_height_m':.065,'drain_height_m':.042,'actual_open_grate_slots':12,'slot_width_m':.004,'drain_well_depth_m':.027,'note':'Local fixture geometry only; no claim of plumbing simulation or complete room collision certification.'})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r61.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'trigger':'Full39 direct/blind review: solid blank shower trays and unreadable drainage. Source probe confirmed factory solid tray has no drain aperture. Existing shower head/mixer meshes do exist; their visual visibility remains unresolved.','changes':records,'base_r60_lighting_status':'conditional trial, not full-scene adoption','photorealism_accepted':False,'requires':'Saved-source audits and identical-camera wetroom comparison before adoption'},indent=2));print('Saved',out,flush=True)
