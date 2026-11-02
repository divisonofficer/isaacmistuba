"""Diagnostic only:pillow shader Normal disconnected,all geometry/colour/roughness/light retained."""
import bpy,runpy,json,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=ref/'pillow_normal_diagnostic_r53';out.mkdir(exist_ok=True);src=Path(bpy.data.filepath);sha=hashlib.sha256(src.read_bytes()).hexdigest();copies={};changes=[]
for o in bpy.data.objects:
 if o.get('bed_pillow_kind') not in ['white','teal']:continue
 old=o.data.materials[0]
 if old.name not in copies:
  m=old.copy();m.name='Diagnostic_geometry_normal_only_'+old.name;bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');links=list(bs.inputs['Normal'].links);assert links
  for l in links:m.node_tree.links.remove(l)
  copies[old.name]=m
 o.data=o.data.copy();o.data.materials[0]=copies[old.name];changes.append({'object':o.name,'original_material':old.name,'diagnostic_material':copies[old.name].name})
assert len(changes)==8;meta={'kind':'diagnostic_pillow_Normal_disconnected_only','source':str(src),'source_sha256':sha,'saved_candidate':False,'overrides':changes,'note':'Only native bed pillows;duvet andother materials retain original Normal. No geometry,colour,roughness orlight edit.'};(out/'diagnostic_override.json').write_text(json.dumps(meta,indent=2));sys.argv=[str(Path(__file__).with_name('render.py')),'--','--views',str(ref/'furniture_r53_bed_pressure_reverse/views.json'),'--out',str(out/'candidate'),'--width','1280','--samples','48'];runpy.run_path(str(Path(__file__).with_name('render.py')),run_name='__main__');assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;meta['render_finished_source_unchanged']=True;(out/'diagnostic_override.json').write_text(json.dumps(meta,indent=2))
