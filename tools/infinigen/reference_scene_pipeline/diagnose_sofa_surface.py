"""Same-source flat-normal ablation: distinguish albedo pattern from bump engraving."""
import bpy,sys,argparse,json,hashlib,runpy,os,datetime
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--views',type=Path,required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.out.mkdir(exist_ok=True);state=a.out/'job.json';assert not state.exists();source=Path(bpy.data.filepath);sha=hashlib.sha256(source.read_bytes()).hexdigest();rows=[]
for m in bpy.data.materials:
 if not m.use_nodes or not m.name.startswith(('ir_sec_fabric','ir_sec_cushion','ir_sec_pillow')):continue
 for bs in m.node_tree.nodes:
  if bs.type!='BSDF_PRINCIPLED':continue
  for link in list(bs.inputs['Normal'].links):rows.append({'material':m.name,'previous_normal_node':link.from_node.name});m.node_tree.links.remove(link)
assert rows;views=[v for v in json.loads(a.views.read_text()) if v['name']=='101_sofa_material_close'];assert len(views)==1
for v in views:v.update(render_width=1280,samples=48)
vf=a.out/'views.json';vf.write_text(json.dumps(views,indent=2));doc={'pid':os.getpid(),'phase':'rendering','source':str(source),'source_sha256':sha,'device':'CPU','override':'disconnect sofa material normal only;geometry/albedo/roughness/lights/camera unchanged'};state.write_text(json.dumps(doc,indent=2));renderer=Path(__file__).with_name('render.py')
try:
 dest=a.out/'flat_normal';sys.argv=[str(renderer),'--','--views',str(vf),'--out',str(dest),'--width','1280','--samples','48','--threads','16'];runpy.run_path(str(renderer),run_name='__main__');receipt=dest/'render_receipt.json';r=json.loads(receipt.read_text());r['diagnostic_shader_override']={'disconnected_channels':rows,'source_saved':False,'meaning':'native geometric/smooth shading normal;no micro normal','driver':str(Path(__file__).resolve()),'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()};receipt.write_text(json.dumps(r,indent=2));doc['phase']='rendered_visual_review_pending'
except Exception as e:doc.update(phase='failed',error=str(e));raise
finally:doc['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();state.write_text(json.dumps(doc,indent=2));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha
