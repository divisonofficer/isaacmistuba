"""Source-bound126/128 living pairs, unfinished review stays explicit."""
from pathlib import Path
from PIL import Image
import json,html,hashlib,datetime,os
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';out=d/'wood115_review';out.mkdir(exist_ok=True);views=json.loads((d/'wood115_matched_views.json').read_text());receipts=[];jobs=[];sections=[];pairs=[]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for folder in ['full_suite_r114_cpu','wood115_candidate_cpu']:
 p=d/folder;jobs.append(json.loads((p/'job.json').read_text()) if (p/'job.json').exists() else {});q=p/'candidate/render_receipt.json';a=json.loads(q.read_text()) if q.exists() else None
 if a:assert sha(a['source'])==a['source_sha256']
 receipts.append(a)
for i,v in enumerate(views):
 fs=[next((f for f in (a or {}).get('frames',[]) if f['name']==v['name']),None) for a in receipts];cells=[]
 for label,f in zip(['A114','B115'],fs):
  body='<p>CPU 렌더 진행 · 완료 영수증 대기</p>'
  if f:
   src=Path(f['path']);assert sha(src)==f['sha256'];jpg=out/(label+'_'+v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1400,1050));im.save(jpg,quality=89);body='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+jpg.name+'"></a>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 if all(fs):
  for k in ['camera','width','height','samples']:assert fs[0][k]==fs[1][k]
  for k in ['device','renderer_sha256','lighting_policy','lighting_overrides','render_threads','denoising']:assert receipts[0][k]==receipts[1][k]
  pairs.append({'name':v['name'],'baseline':fs[0],'candidate':fs[1]})
 sections.append('<section id="v'+str(i)+'"'+(' hidden' if i else '')+'><h2>'+html.escape(v['name'])+'</h2><div class="pair">'+''.join(cells)+'</div></section>')
(out/'evidence.json').write_text(json.dumps({'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'required_pairs':3,'completed_pairs':len(pairs),'pairs':pairs,'jobs':jobs,'visual_review_complete':(out/'independent_coverage_verified.json').exists(),'accepted':False,'scope':'Same cameras1280px48samples CPU6. Source114 existing completed suite baseline;115 finish/UV only. Photographic oak source is not scanner/measured-BRDF certified. Geometry and manufacturing defects remain open.'},indent=2))
page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>사무실115 목재 마감 시험</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}button{padding:10px;margin:4px}section[hidden]{display:none}</style><h1>사무실115 · 책상/테이블/수납장 목재 마감 시험</h1><p>A114/B115 '+str(len(pairs))+'/3쌍.기존114 전체 렌더 중 동일 카메라·1280px·48샘플·CPU6·렌더러/조명정책 일치 원본을 기준으로 사용합니다.직접 원본6장·참조3장 및 히스토리 없는 독립검수 완료:오픈오피스/회의실 A선호2,개별실 B선호1.115 일괄채택 보류·전체 실사성 미달입니다.</p><p>24개 기존 가구의 선택 목재 슬롯만1m 사진 기반 오크 albedo/roughness/GLnormal로 교체했습니다.실제 각 면 길이에 맞춘 metre UV와 tangent normal을 사용하며 추가 noise·색조/노출/조명 조절은 없습니다.105 탕비실 사진 기반 캐비닛·바닥·문·비목재 슬롯은 유지합니다.</p><p>형상/좌표가 그대로인 마감 시험으로 가구 제조 구조·단순한 패널 다리·천장/외부 전망·사용 반복 문제는 미해결입니다.노드 존재/메쉬 불변만으로 실사 개선을 주장하지 않습니다.</p><p><a href="blind_visual_review.json">독립9장 혼합 판정</a> · <a href="visual_review.json">직접 전체 비평</a> · <a href="evidence.json">동일조건·진행·원본</a> · <a href="../wood115_saved_audit.json">저장본 재오픈 형상/좌표/기존UV/비대상슬롯 검사</a> · <a href="../wood115_build.json">변경24개·사진 텍스처 출처/원래 크기</a> · <a href="../full_suite_r114_cpu/report.html">기준114 전체21뷰·미달</a> · <a href="../fine_current.html">현재 현황</a></p><nav>'+''.join('<button data-tab="v'+str(i)+'">'+html.escape(v['name'])+'</button>' for i,v in enumerate(views))+'</nav>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>';assert len(page.encode())<30000;(out/'report.html').write_text(page);print('WOOD115_REPORT',len(pairs),len(page.encode()))
