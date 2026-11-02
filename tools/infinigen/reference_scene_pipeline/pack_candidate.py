"""Pack self-contained review copies, preserving all candidate sources."""
import argparse,hashlib,json,platform,sys
from pathlib import Path
import bpy
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]);assert not a.out.exists();source_hash=hashlib.sha256(a.blend.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()))
assert not list(bpy.data.libraries),'Linked libraries must be resolved before packaging'
bpy.ops.file.pack_all();images=[];missing=[]
for im in bpy.data.images:
 if im.source not in ('FILE','TILED'):continue
 packed=bool(im.packed_file or len(im.packed_files));images.append({'name':im.name,'path':im.filepath,'packed':packed,'users':im.users})
 if im.users and not packed:missing.append(im.name)
assert not missing,missing
bpy.ops.wm.save_as_mainfile(filepath=str(a.out.resolve()));assert hashlib.sha256(a.blend.read_bytes()).hexdigest()==source_hash
result={'source':str(a.blend.resolve()),'source_sha256':source_hash,'packed':str(a.out.resolve()),'packed_sha256':hashlib.sha256(a.out.read_bytes()).hexdigest(),'images':images,'missing_used_images':missing,'linked_libraries':0,'source_unchanged':True,'hostname':platform.node(),'python':sys.executable,'blender_version':bpy.app.version_string,'visual_acceptance':False,'reopen_render_pending':True};a.manifest.write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='images'}))
