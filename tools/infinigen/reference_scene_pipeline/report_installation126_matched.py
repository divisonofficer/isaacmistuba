"""Small receipt-backed installation gallery, physical scope and visual uncertainty separated."""
from pathlib import Path
import json,hashlib,html,os,datetime
from PIL import Image
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'installation126_review';out.mkdir(exist_ok=True);views=json.loads((d/'installation126_matched_views.json').read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();receipts=[]
for folder in ['installation126_baseline_cpu','installation126_candidate_cpu']:
 p=d/folder/'candidate/render_receipt.json';a=json.loads(p.read_text()) if p.exists() else None
 if a:assert sha(a['source'])==a['source_sha256']
 receipts.append(a)
sections=[];pairs=[]
for i,v in enumerate(views):
 fs=[next((f for f in (a or {}).get('frames',[]) if f['name']==v['name']),None) for a in receipts];cells=[]
 for label,f in zip(['A125','B126'],fs):
  body='<p>CPU 렌더 진행</p>'
  if f:
   src=Path(f['path']);assert sha(src)==f['sha256'];jpg=out/(label+'_'+v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1400,1050));im.save(jpg,quality=89);body='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+jpg.name+'"></a>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 if all(fs):
  for k in ['camera','width','height','samples']:assert fs[0][k]==fs[1][k]
  for k in ['device','renderer_sha256','lighting_policy','lighting_overrides','render_threads','denoising']:assert receipts[0][k]==receipts[1][k]
  pairs.append({'name':v['name'],'baseline':fs[0],'candidate':fs[1]})
 sections.append('<section id="v'+str(i)+'"'+(' hidden' if i else '')+'><h2>'+html.escape(v['name'])+'</h2><div class="pair">'+''.join(cells)+'</div></section>')
proof={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'required_pairs':6,'complete_pairs':len(pairs),'pairs':pairs,'same_camera_resolution_samples_cpu_threads_renderer_policy':True,'visual_review_complete':(out/'independent_coverage_verified.json').exists(),'accepted':False};(out/'evidence.json').write_text(json.dumps(proof,indent=2));summary=json.loads((out/'visual_review.json').read_text()).get('summary','') if (out/'visual_review.json').exists() else '욕실 넓은뷰2쌍 직접 확인:바닥의 잘못된 흰 박스가 없어져 바닥 노출이 정상화됐지만 평탄한 회색 타일/단순 수납장/도기·목재 디테일은 여전히 미달. 나머지 근접 뷰 및 독립 검수 전.';blind='<a href="blind_visual_review.json">독립 원본 검수</a> · ' if (out/'blind_visual_review.json').exists() else '독립 검수 대기 · ';page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>주거126 문틀 설치·실제 등기구</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}button{padding:10px;margin:4px}section[hidden]{display:none}</style><h1>주거126 · 문틀15곳/실제 욕실등2개</h1><p>같은 카메라·1280px·48샘플·CPU8·AgX노출0 비교 '+str(len(pairs))+'/6쌍. '+summary+'</p><p>15개 native 문틀 하단만80mm 아래로 설치,문짝/손잡이/상부 정점·토폴로지·재질 보존. 바닥에 잘못 놓인42cm 박스2개는 native6294면·직경10.49cm 실제 매입등으로 교체. 실제 천장 구멍/트림/높이와 기존18W transport설정 보존 확인(광원 크기/분포는 변경,광도 측정값 아님).18개 정적 출입구 표면 스크린의 충돌 없는 곳은1→13개. 제외8문/가구·화분·동적문·전체동선은 별도 미해결입니다.</p><p>125 거실 배치의 독립 혼합 판정과 TV/소파·화장실 시선 문제는126에도 남습니다. 국소 설치/바닥 정리를 전체 실사성 합격으로 보지 않습니다.</p><p>'+blind+'<a href="evidence.json">카메라/원본 해시</a> · <a href="../portal_installation126_build.json">실제 수정</a> · <a href="../portal_installation126_saved_audit.json">저장본·원인 선택자 검증</a> · <a href="../portals126_surface_screen.json">현재18출입 표면 반례</a> · <a href="../navigation126_preflight/report.html">현재 층 전체 스크린</a> · <a href="../living125_review/report.html">125 혼합 비평</a> · <a href="../fine_current.html">현재 현황</a></p><nav>'+''.join('<button data-tab="v'+str(i)+'">'+label+'</button>' for i,label in enumerate(['101욕실','102욕실','101문턱','102문턱','101등기구','102등기구']))+'</nav>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>';assert len(page.encode())<30000;(out/'report.html').write_text(page);print('INSTALLATION126_REPORT',len(pairs),6)
