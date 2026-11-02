"""Saved positive controls and in-memory negative controls; never changes snapshots."""
import bpy,json,argparse,hashlib
from pathlib import Path
from compact_wc_contract import verify_compact_body,verify_compact_flush

def main():
 p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();src=a.blend.resolve();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));ref=Path(__file__).resolve().parents[3]/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';cases=[];compact=[o for o in bpy.data.objects if o.get('wc_variant')=='native_concealed_cistern'];assert len(compact)==2
 for o in compact:
  body=verify_compact_body(o,ref);flush=verify_compact_flush(o,ref);assert body['pass'] and flush['pass'];cases.append({'case':'saved_positive','object':o.name,'body':body,'flush':flush})
 o=compact[0];original=o.data;o.data=original.copy();o.data.vertices[0].co.x+=.01;result=verify_compact_body(o,ref);assert not result['pass'];o.data=original;cases.append({'case':'changed_body_geometry_rejected','result':result})
 part=next(o for o in bpy.data.objects if o.get('wc_flush_parent_key')==compact[0]['program_key']);matrix=part.matrix_world.copy();part.location.x+=.01;bpy.context.view_layer.update();result=verify_compact_flush(compact[0],ref);assert not result['pass'];part.matrix_world=matrix;bpy.context.view_layer.update();cases.append({'case':'detached_flush_part_rejected','result':result})
 standard=next(o for o in bpy.data.objects if o.get('program_key')=='101_bathroom2_wc');assert not standard.get('wc_variant');standard['wc_variant']='native_concealed_cistern';standard['wc_compact_prototype_sha256']=compact[0]['wc_compact_prototype_sha256'];result=verify_compact_body(standard,ref);assert not result['pass'];cases.append({'case':'standard_body_spoofed_tag_rejected','result':result});assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
 a.out.write_text(json.dumps({'source':str(src),'source_sha256':sha,'actual_saved_positive_count':2,'actual_in_memory_negative_count':3,'cases':cases,'snapshots_unchanged':True,'photorealism_accepted':False,'scope':'Exact reviewed body andflush placement contract guards. No whole-scene,door-sweep orfluid certification.'},indent=2));print('Verified2 saved positives and3 in-memory negatives',flush=True)
if __name__=='__main__':main()
