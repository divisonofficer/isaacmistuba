"""Native USD import probe; does not modify any office/residential scene."""
import bpy,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[3];p=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_asset_candidates';src=p/'moorelane_candidates_resolved.usdc';out=p/'moorelane_candidates_imported.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.read_factory_settings(use_empty=True);bpy.ops.wm.usd_import(filepath=str(src),import_cameras=False,import_lights=False,import_materials=True);meshes=[o for o in bpy.data.objects if o.type=='MESH'];images=[]
for im in bpy.data.images:
 if im.source!='FILE':continue
 path=Path(bpy.path.abspath(im.filepath));exists=path.is_file();images.append({'name':im.name,'filepath':str(path),'exists':exists,'size':list(im.size)})
 if exists:im.pack()
rows=[{'name':o.name,'vertices':len(o.data.vertices),'polygons':len(o.data.polygons),'materials':[s.material.name if s.material else None for s in o.material_slots]} for o in meshes];assert len(rows)>=15,(len(rows),rows);bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(p/'blender_import_probe.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'blend':str(out),'mesh_count':len(rows),'meshes':rows,'images':images,'missing_images':[x for x in images if not x['exists']],'photorealism_accepted':False,'scene_integration':False,'scope':'Real source assemblies imported with native USD preview materials. Packed resolved image dependencies. Unbound original meshes and visual suitability remain to inspect; no proxy replacement in approved scenes.'},indent=2)+'\n');print('Imported real asset library',len(rows),flush=True)
