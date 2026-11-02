"""Source-bound126/128 living pairs, unfinished review stays explicit."""
from pathlib import Path
from PIL import Image
import json,html,hashlib,datetime,os
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'wall129_review';out.mkdir(exist_ok=True);views=json.loads((d/'wall129_matched_views.json').read_text());receipts=[];jobs=[];sections=[];pairs=[]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for folder in ['compact128_candidate_cpu','wall129_candidate_cpu']:
 p=d/folder;jobs.append(json.loads((p/'job.json').read_text()) if (p/'job.json').exists() else {});q=p/'candidate/render_receipt.json';a=json.loads(q.read_text()) if q.exists() else None
 if a:assert sha(a['source'])==a['source_sha256']
 receipts.append(a)
for i,v in enumerate(views):
 fs=[next((f for f in (a or {}).get('frames',[]) if f['name']==v['name']),None) for a in receipts];cells=[]
 for label,f in zip(['A128','B129'],fs):
  body='<p>CPU 렌더 진행 · 완료 영수증 대기</p>'
  if f:
   src=Path(f['path']);assert sha(src)==f['sha256'];jpg=out/(label+'_'+v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1400,1050));im.save(jpg,quality=89);body='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+jpg.name+'"></a>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 if all(fs):
  for k in ['camera','width','height','samples']:assert fs[0][k]==fs[1][k]
  for k in ['device','renderer_sha256','lighting_policy','lighting_overrides','render_threads','denoising']:assert receipts[0][k]==receipts[1][k]
  pairs.append({'name':v['name'],'baseline':fs[0],'candidate':fs[1]})
 sections.append('<section id="v'+str(i)+'"'+(' hidden' if i else '')+'><h2>'+html.escape(v['name'])+'</h2><div class="pair">'+''.join(cells)+'</div></section>')
(out/'evidence.json').write_text(json.dumps({'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'required_pairs':2,'completed_pairs':len(pairs),'pairs':pairs,'jobs':jobs,'visual_review_complete':(out/'independent_coverage_verified.json').exists(),'accepted':False,'scope':'Same cameras1280px48samples CPU8. Architecture duplicate-face removal only; source128 furniture/lighting retained. No whole-room reference or photo acceptance.'},indent=2))
page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>주거129 벽 접합 정리</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}button{padding:10px;margin:4px}section[hidden]{display:none}</style><h1>주거129 · 실제 중복 벽면 제거</h1><p>A128/B129 동일조건 '+str(len(pairs))+'/2쌍.CPU8·1280px·48샘플.직접/독립 시각검수 대기·미채택.</p><p>128 역방향에서 검은 띠 위치의 광선이 새/기존 벽의 같은 위치에 겹쳐 닿았습니다.새 가림벽 끝을 실제 기존 벽 시작Y8.9854555m에 맞춰 양쪽 주요 겹침 면적 약1.024m²를0으로 줄였습니다.코어 WC의 겹친 기존 벽 두 개는 EXACT boolean union으로 실제 하나의 폐합 솔리드로 정리했습니다.단순 색조/어두움/불투명 덮개 수정이 아닙니다.</p><p>129 저장 시 두 코어 결합 솔리드는 nonmanifold edge0이며 다른 가구 원본 메쉬·배치는 유지했습니다.재오픈/동선·렌더·참조 검수는 별도이며 이 조건만으로 실사 개선을 주장하지 않습니다.침실2의 부적합한 native 양개문과 전체 층 단절,직물/외부/제조 디테일은 미해결입니다.</p><p><a href="evidence.json">동일조건·현재 진행</a> · <a href="../wall_joins129_build.json">실제129 변경/해시</a> · <a href="../media128_black_strip_surface_probe.json">128 검은 띠 위치 광선</a> · <a href="../media128_coplanar_wall_diagnosis.json">128 실제 동일평면 교차</a> · <a href="../wall_joins129_initial_guard_failure.json">초기 잘못된 면수 가정 차단</a> · <a href="../compact128_review/report.html">128 직접/독립14장 국소 판정</a> · <a href="../fine_current.html">현재 현황</a></p><nav>'+''.join('<button data-tab="v'+str(i)+'">'+html.escape(v['name'])+'</button>' for i,v in enumerate(views))+'</nav>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>';assert len(page.encode())<30000;(out/'report.html').write_text(page);print('WALL129_REPORT',len(pairs),len(page.encode()))
