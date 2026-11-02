"""Restore exact original GLB PNG bytes; no invented colors/material changes."""
import bpy,json,hashlib,struct,re
from pathlib import Path
root=Path(__file__).resolve().parents[3];p=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_chair_candidates';manifest=json.loads((p/'asset_candidates_manifest.json').read_text());src=p/'review_studio.blend';out=p/'review_studio_textures_fixed.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for entry in manifest['assets']:
 file=Path(entry['path'])
 if file.suffix!='.glb':continue
 raw=file.read_bytes();assert hashlib.sha256(raw).hexdigest()==entry['copied_sha256'];n,kind=struct.unpack_from('<II',raw,12);assert kind==0x4e4f534a;doc=json.loads(raw[20:20+n]);bn,btype=struct.unpack_from('<II',raw,20+n);assert btype==0x004e4942;payload=raw[28+n:28+n+bn];paths={}
 for idx,image in enumerate(doc['images']):
  assert image['mimeType']=='image/png';view=doc['bufferViews'][image['bufferView']];assert view['buffer']==0;offset=view.get('byteOffset',0);data=payload[offset:offset+view['byteLength']];assert data.startswith(b'\x89PNG\r\n\x1a\n');dest=file.parent/'textures'/f'original_image_{idx}.png';dest.parent.mkdir(exist_ok=True)
  if dest.exists():assert dest.read_bytes()==data
  else:dest.write_bytes(data)
  paths[idx]=(dest,hashlib.sha256(data).hexdigest())
 objects=[o for o in bpy.data.objects if o.get('original_asset_id')==entry['id']];assert objects;images={};nodes=[]
 for o in objects:
  for slot in o.material_slots:
   if slot.material and slot.material.use_nodes:nodes.extend(n for n in slot.material.node_tree.nodes if n.type=='TEX_IMAGE' and n.image)
 assert nodes
 for node in nodes:
  old=node.image;match=re.fullmatch(r'Image_(\d+)(?:\.\d+)?',old.name);assert match,old.name;idx=int(match.group(1));key=(idx,old.colorspace_settings.name)
  if key not in images:
   path,digest=paths[idx];new=bpy.data.images.load(str(path),check_existing=False);new.colorspace_settings.name=key[1];assert min(new.size)>0;new.pack();assert new.packed_file;assert hashlib.sha256(new.packed_file.data).hexdigest()==digest;images[key]=new;rows.append({'asset_id':entry['id'],'source_image_index':idx,'original_png':str(path),'png_sha256':digest,'packed_sha256':hashlib.sha256(new.packed_file.data).hexdigest(),'colorspace':key[1],'dimensions':list(new.size)})
  node.image=images[key]
 for im in list(bpy.data.images):
  if im.name.startswith('Image_') and im.users==0:bpy.data.images.remove(im)
for m in bpy.data.materials:
 if not m.use_nodes:continue
 for node in m.node_tree.nodes:
  if node.type=='TEX_IMAGE' and node.image:assert node.image.packed_file, node.image.name
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(p/'embedded_texture_repair.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'repairs':rows,'change':'Only texture image datablocks relinked to exact original GLB embeddedPNG bytes andpacked. Native geometry,UV,shader parameters,lights,cameras andsource GLBs unchanged.','failure_evidence':'review_render ABO renders aremagenta;review_scope recorded packed:false for6 original embeddedimages. Original bad studio/render preserved.','photorealism_accepted':False,'requires':'Reopen actual savedfixed file andverify packed-image hashes beforeRGB;then sixsame-camera visual reviews.'},indent=2)+'\n');print('Fixed original embeddedPNG packing',len(rows),flush=True)
