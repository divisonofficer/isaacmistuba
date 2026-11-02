"""Six source-matched living/access pairs, with held placement attempts preserved."""
from pathlib import Path
import json,hashlib,os,html,datetime
from PIL import Image
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'living125_review';out.mkdir(exist_ok=True);views=json.loads((d/'living125_matched_views.json').read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();receipts=[]
for folder in ['living125_baseline_cpu','living125_candidate_cpu']:
 p=d/folder/'candidate/render_receipt.json';a=json.loads(p.read_text()) if p.exists() else None
 if a:assert sha(a['source'])==a['source_sha256']
 receipts.append(a)
sections=[];pairs=[]
for i,v in enumerate(views):
 fs=[next((f for f in (a or {}).get('frames',[]) if f['name']==v['name']),None) for a in receipts];cells=[]
 for label,f in zip(['A122','B125'],fs):
  body='<p>CPU 렌더 진행</p>'
  if f:
   src=Path(f['path']);assert sha(src)==f['sha256'];p=out/(label+'_'+v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1400,1050));im.save(p,quality=89);body='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+p.name+'"></a>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 if all(fs):
  for k in ['camera','width','height','samples']:assert fs[0][k]==fs[1][k]
  for k in ['device','renderer_sha256','lighting_policy','lighting_overrides','render_threads','denoising']:assert receipts[0][k]==receipts[1][k]
  pairs.append({'name':v['name'],'baseline':fs[0],'candidate':fs[1]})
 sections.append('<section id="v'+str(i)+'"'+(' hidden' if i else '')+'><h2>'+html.escape(v['name'])+'</h2><div class="pair">'+''.join(cells)+'</div></section>')
a={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'required_pairs':6,'completed_pairs':len(pairs),'pairs':pairs,'visual_review_complete':(out/'independent_coverage_verified.json').exists(),'accepted':False,'scope':'Same-camera1280px48sample CPU pairs. Media native scale and geometry unchanged, moved to north walls; one native ficus moved. Source122 full-floor navigation failed;125 full-floor screen/visual reference tradeoffs pending. Two exact600mm living routes clear but not whole-floor navigation acceptance.'};(out/'evidence.json').write_text(json.dumps(a,indent=2));page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>주거125 거실 출입 회복 시험</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}button{padding:10px;margin:4px}section[hidden]{display:none}</style><h1>주거125 · 실제 미디어월 재배치</h1><p>A122/B125 동일조건 '+str(len(pairs))+'/6쌍 완료.1280px·48샘플·동일 카메라/조명/노출. 원본12장+참조2장 직접·독립검수 완료:출입2쌍 B선호·거실2쌍 동률·역방향2쌍 A선호. TV 시청 방향·화장실 시선 노출·참조 구도·실사성 미달.</p><p>122에서 실제 TV 미디어월이 양쪽 거실 출입구를 막았습니다.123 남벽 배치는 소파/걸레받이 충돌로 폐기.124 북벽 배치는101식물 충돌로 보류.125는 native 미디어월 크기를 유지하고 식물을(5.6,8.2)m로 이동했습니다. 두 실제600mm 출입 경로·바닥 중심 표본은 통과했지만 전체 층/동적 문/지지/참조 배치·실사성 승인과 구분합니다.</p><p><a href="blind_visual_review.json">독립 원본14장 혼합 판정</a> · <a href="visual_review.json">전체 직접 비평</a> · <a href="../navigation122_preflight/report.html">전체 동선 반례·폐기 시도</a> · <a href="../living125_access_build.json">native 식물 실배치</a> · <a href="../living124_media_relocation_build.json">미디어월 크기·포즈</a> · <a href="../living125_portal_center_route_audit.json">현재 출입 경로 실제 삼각형/바닥 검사</a> · <a href="../living125_saved_audit.json">저장본 native 형상/공간 크기·실제 바닥27표본</a> · <a href="../navigation125_preflight/report.html">125 층 전체 재검사:부분 회복·잔존 분리</a> · <a href="evidence.json">렌더 동일조건/원본 해시</a> · <a href="../fine_current.html">현재 보고서</a></p><nav>'+''.join('<button data-tab="v'+str(i)+'">'+html.escape(v['name'])+'</button>' for i,v in enumerate(views))+'</nav>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>';assert len(page.encode())<30000;(out/'report.html').write_text(page);print('LIVING125_REPORT',len(pairs),6)
