"""Source-bound126/128 living pairs, unfinished review stays explicit."""
from pathlib import Path
from PIL import Image
import json,html,hashlib,datetime,os
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'compact128_review';out.mkdir(exist_ok=True);views=json.loads((d/'living125_matched_views.json').read_text());receipts=[];jobs=[];sections=[];pairs=[]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for folder in ['compact128_baseline_cpu','compact128_candidate_cpu']:
 p=d/folder;jobs.append(json.loads((p/'job.json').read_text()) if (p/'job.json').exists() else {});q=p/'candidate/render_receipt.json';a=json.loads(q.read_text()) if q.exists() else None
 if a:assert sha(a['source'])==a['source_sha256']
 receipts.append(a)
for i,v in enumerate(views):
 fs=[next((f for f in (a or {}).get('frames',[]) if f['name']==v['name']),None) for a in receipts];cells=[]
 for label,f in zip(['A126','B128'],fs):
  body='<p>CPU 렌더 진행 · 완료 영수증 대기</p>'
  if f:
   src=Path(f['path']);assert sha(src)==f['sha256'];jpg=out/(label+'_'+v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1400,1050));im.save(jpg,quality=89);body='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+jpg.name+'"></a>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 if all(fs):
  for k in ['camera','width','height','samples']:assert fs[0][k]==fs[1][k]
  for k in ['device','renderer_sha256','lighting_policy','lighting_overrides','render_threads','denoising']:assert receipts[0][k]==receipts[1][k]
  pairs.append({'name':v['name'],'baseline':fs[0],'candidate':fs[1]})
 sections.append('<section id="v'+str(i)+'"'+(' hidden' if i else '')+'><h2>'+html.escape(v['name'])+'</h2><div class="pair">'+''.join(cells)+'</div></section>')
(out/'evidence.json').write_text(json.dumps({'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'required_pairs':6,'completed_pairs':len(pairs),'pairs':pairs,'jobs':jobs,'visual_review_complete':(out/'independent_coverage_verified.json').exists(),'accepted':False,'scope':'Same cameras1280px48samples CPU8. Geometry/finishes/layout change, including removal of old furniture mesh LEDs, so not lighting-isolation test. Full source116 images do not cover128.'},indent=2))
page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>주거128 · 거실 방향/프라이버시</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}button{padding:10px;margin:4px}section[hidden]{display:none}</style><h1>주거128 · 실제 compact TV/TV장·가림벽</h1><p>A126/B128 동일조건 '''+str(len(pairs))+'''/6쌍 완료.1280px·48샘플·CPU8. 원본12장·참조2장 직접/히스토리 없는 독립검수 완료:B선호4·동률2.역방향 TV시청방향·변기 가림은 국소개선.전방 빈 벽/균일한 러그·소파와 검은 수직띠·참조 차이가 남아 전체 실사성/동선 합격 전입니다.</p><p>127은 라이브러리 변환 누락으로 TV가 수평 배치되어 두 통로를 침범했습니다. 실패 후보를 보존하고128에서 실제 native 스튜디오를 다시 열어 변환을 복원했습니다. TV 실크기:폭1.323m·높이0.708m·두께0.063m.101 오크/102 원래 짙은 목재, 시청방향·가림벽·식물 배치는127과 같은 계획입니다.</p><p>재오픈 raw 메쉬/크기·TV장 하단 실제 바닥 접촉·TV 후면 벽 간격은 제한 범위 통과. 양쪽600mm 출입→거실→private hall 제안 경로는 실제 렌더 메쉬 표면/정점 충돌 없이 검사됐습니다. 벽 고정 하드웨어·동적 문·전체 층 동선·실사성 승인은 별도 미완료입니다.</p><p><a href="evidence.json">렌더 진행/동일조건</a> · <a href="visual_review.json">직접14장 전체 비평</a> · <a href="blind_visual_review.json">독립14장 국소 판정</a> · <a href="../navigation128_preflight/report.html">128 전체 지상층 동선</a> · <a href="../native_media_products/library_pose_preflight.json">라이브러리 변환 오류 실제 재현/차단</a> · <a href="../compact_media128_build.json">128 제작 기록</a> · <a href="../compact_media128_saved_audit.json">저장본 크기/접촉</a> · <a href="../private128_reserved_route_audit.json">128 실제 통로</a> · <a href="../private127_reserved_route_audit.json">127 실패 반례</a> · <a href="../living125_review/report.html">125 독립 혼합 판정</a> · <a href="../fine_current.html">현재 현황</a></p><nav>'''+''.join('<button data-tab="v'+str(i)+'">'+html.escape(v['name'])+'</button>' for i,v in enumerate(views))+'</nav>'+''.join(sections)+'''<script>for(const b of document.querySelectorAll('[data-tab]'))b.onclick=()=>{for(const s of document.querySelectorAll('section'))s.hidden=s.id!==b.dataset.tab}</script></html>''';assert len(page.encode())<30000;(out/'report.html').write_text(page);print('COMPACT128_REPORT',len(pairs),len(page.encode()))
