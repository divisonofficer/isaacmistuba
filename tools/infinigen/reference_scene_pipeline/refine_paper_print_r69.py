"""Readable brandless ream packaging graphics; preserve measured pack and support geometry."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';source=base/'scene_candidate_r68.blend';out=base/'scene_candidate_r69.blend';assert not out.exists();sha=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));ink=bpy.data.materials['R68_navy_print_ink'];white=bpy.data.materials.new('R69_wrapper_reverse_white_ink');white.use_nodes=True;white.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.82,.81,.77,1);white.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.6;records=[]
def panel(name,points,material,key):
 me=bpy.data.meshes.new(name);me.from_pydata(points,[],[(0,1,2,3)]);me.materials.append(material);o=bpy.data.objects.new(name,me);bpy.context.scene.collection.objects.link(o);o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=key;o['audit_kind']='detail'
for key in ['west_paper_stack','east_paper_stack']:
 body=next(o for o in bpy.data.objects if o.get('program_key')==key);pts=[body.matrix_world@Vector(c) for c in body.bound_box];x0,x1=min(p.x for p in pts),max(p.x for p in pts);y0,y1=min(p.y for p in pts),max(p.y for p in pts);z0,z1=min(p.z for p in pts),max(p.z for p in pts);cx,cy=(x0+x1)/2,(y0+y1)/2;band_end=x0+.082;eps=.00012
 for o in list(bpy.data.objects):
  if o.get('program_key')==key+'_printed_label':bpy.data.objects.remove(o,do_unlink=True)
 panel(key+'_top_ink',[(x0+.001,y0+.001,z1+eps),(band_end,y0+.001,z1+eps),(band_end,y1-.001,z1+eps),(x0+.001,y1-.001,z1+eps)],ink,key+'_top_ink')
 panel(key+'_end_ink',[(x0-eps,y0+.001,z0+.001),(x0-eps,y1-.001,z0+.001),(x0-eps,y1-.001,z1-.001),(x0-eps,y0+.001,z1-.001)],ink,key+'_end_ink')
 for sign,y in [(-1,y0-eps),(1,y1+eps)]:panel(key+'_side_ink_'+str(sign),[(x0+.001,y,z0+.001),(band_end,y,z0+.001),(band_end,y,z1-.001),(x0+.001,y,z1-.001)],ink,key+'_side_ink_'+str(sign))
 for suffix,text,location,size,mat in [('format','A4',((x0+band_end)/2,cy,z1+.00022),.036,white),('spec','OFFICE PAPER\n80 GSM\n500 SHEETS',((band_end+x1)/2,cy,z1+.00022),.016,ink)]:
  data=bpy.data.curves.new(key+'_'+suffix,'FONT');data.body=text;data.align_x='CENTER';data.align_y='CENTER';data.size=size;data.extrude=.00002;obj=bpy.data.objects.new(data.name,data);bpy.context.scene.collection.objects.link(obj);obj.location=location;data.materials.append(mat);obj['reference_scene_owner']='commercial_office_floor_02';obj['program_key']=key+'_'+suffix;obj['audit_kind']='detail'
 records.append({'pack':body.name,'change':'printed navy band wraps top/end/sides; white A4 and larger brandless specification; body and support unmodified'})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r69.json').write_text(json.dumps({'source':str(source),'source_sha256':sha,'candidate':str(out),'packs':records,'photorealism_accepted':False,'requires':'saved checks and same-camera product-identification review'},indent=2));print(out,flush=True)
