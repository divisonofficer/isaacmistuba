"""Combine verified partial GPU14 + completed CPU7 without rewriting original failed job."""
from pathlib import Path
import json,hashlib,shutil,html
from PIL import Image
r=Path(__file__).resolve().parents[3];p=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';g=p/'full_suite_r111_gpu5';c=p/'full_suite_r111_cpu_completion';out=p/'full_suite_r111_mixed';assert not out.exists();gj=json.loads((g/'job.json').read_text());cj=json.loads((c/'job.json').read_text());assert gj['phase']=='yielded_gpu5' and cj.get('exit_code')==0
receipts=[json.loads((d/'candidate/render_receipt.json').read_text()) for d in [g,c]];a,b=receipts
for key in ['source','source_sha256','renderer_sha256','lighting_policy','lighting_overrides','denoising']:assert a[key]==b[key],key
assert hashlib.sha256(Path(a['source']).read_bytes()).hexdigest()==a['source_sha256'];assert b['source_unchanged'];required=json.loads((p/'full_suite_r108_views.json').read_text());expected={v['name']:v for v in required};frames={}
for device,receipt in zip(['OPTIX','CPU'],receipts):
 for f in receipt['frames']:
  assert f['name'] not in frames and f['camera']==expected[f['name']];src=Path(f['path']);assert hashlib.sha256(src.read_bytes()).hexdigest()==f['sha256'];frames[f['name']]={**f,'device':device,'original_path':f['path']}
assert set(frames)==set(expected) and len(frames)==21
(out/'candidate').mkdir(parents=True);cards=[]
for name in expected:
 f=frames[name];src=Path(f['original_path']);dst=out/'candidate'/src.name;shutil.copyfile(src,dst);assert hashlib.sha256(dst.read_bytes()).hexdigest()==f['sha256'];f['path']=str(dst);jpg=out/(name+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1280,1280));im.save(jpg,quality=87);cards.append('<figure><a href="candidate/'+dst.name+'"><img loading="lazy" src="'+jpg.name+'"></a><figcaption>'+html.escape(name)+' · '+f['device']+'</figcaption></figure>')
(out/'evidence.json').write_text(json.dumps({'source':a['source'],'source_sha256':a['source_sha256'],'renderer_sha256':a['renderer_sha256'],'required_view_count':21,'verified_frame_count':21,'frames':[frames[n] for n in expected],'gpu_job_exit_code':gj['exit_code'],'gpu_job_yield_reason':gj['yield_reason'],'cpu_job_exit_code':0,'device_counts':{'OPTIX':14,'CPU':7},'gpu_partial_source_revalidated_current':True,'visual_review_complete':False,'accepted':False,'scope':'Same source/cameras/settings verified. Mixed device suite, not strict all-GPU A/B; device numerical differences possible. GPU job failure preserved.'},indent=2))
(out/'report.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>사무실111 전체21뷰</title><style>body{font:16px/1.6 system-ui;max-width:1400px;margin:auto;padding:20px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:18px}figure{margin:0}img{width:100%}</style><h1>사무실111 · 전체21뷰 · GPU14+CPU7</h1><p>GPU 공유메모리한도로 own작업을 양보한 뒤 미완7뷰만 CPU로 완료했습니다. 같은소스·카메라·샘플·렌더정책과 PNG해시를 확인했습니다. 혼합기기 수치차이는 가능하며, 전체 시각/독립검수는 아직입니다. 승인·승격 없음.</p><a href="evidence.json">프레임별 기기·원본·해시 증거</a><div class="grid">'+''.join(cards)+'</div></html>');print(out/'report.html')
