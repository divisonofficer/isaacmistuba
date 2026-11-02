"""Isolate broad-roughness variation versus micro-normal effects without changing geometry or lighting."""
import bpy,sys,argparse,json,hashlib,runpy,os,datetime
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--views',type=Path,required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.out.mkdir(exist_ok=True);state=a.out/'job.json';assert not state.exists();source=Path(bpy.data.filepath);sha=hashlib.sha256(source.read_bytes()).hexdigest();renderer=Path(__file__).with_name('render.py');m=bpy.data.materials['SinkR31_satin_stainless'];bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');links=m.node_tree.links;rough_from=bs.inputs['Roughness'].links[0].from_socket;normal_from=bs.inputs['Normal'].links[0].from_socket;views=[v for v in json.loads(a.views.read_text()) if v['name']=='breakout_sink_detail'];assert len(views)==1;views[0]['samples']=48;vf=a.out/'views.json';vf.write_text(json.dumps(views,indent=2));doc={'pid':os.getpid(),'phase':'rendering','device':'CPU','source':str(source),'source_sha256':sha,'completed':[]};state.write_text(json.dumps(doc,indent=2))
try:
 for variant in ['flat_roughness','flat_normal']:
  for channel,original in [('Roughness',rough_from),('Normal',normal_from)]:links.new(original,bs.inputs[channel])
  channel='Roughness' if variant=='flat_roughness' else 'Normal'
  for link in list(bs.inputs[channel].links):links.remove(link)
  if variant=='flat_roughness':bs.inputs['Roughness'].default_value=.27
  dest=a.out/variant;sys.argv=[str(renderer),'--','--views',str(vf),'--out',str(dest),'--width','1280','--samples','48','--threads','16'];runpy.run_path(str(renderer),run_name='__main__');receipt=dest/'render_receipt.json';r=json.loads(receipt.read_text());r['diagnostic_shader_override']={'material':m.name,'disconnected_channel':channel,'roughness_default':.27 if variant=='flat_roughness' else None,'normal_unlinked_means':'use native geometric/smooth shading normal, no micro bump' if variant=='flat_normal' else None,'driver':str(Path(__file__).resolve()),'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'geometry_lights_camera':'unchanged'};receipt.write_text(json.dumps(r,indent=2));doc['completed'].append(variant);state.write_text(json.dumps(doc,indent=2))
 doc['phase']='rendered_visual_review_pending'
except Exception as e:doc['phase']='failed';doc['error']=str(e);raise
finally:doc['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();state.write_text(json.dumps(doc,indent=2));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha
