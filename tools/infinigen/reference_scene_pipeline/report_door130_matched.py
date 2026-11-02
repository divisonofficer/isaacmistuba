"""Source-bound129/130 bedroom entry pairs; local review is separate from full acceptance."""
from pathlib import Path
from PIL import Image
import json,html,hashlib,datetime,os
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'door130_review';out.mkdir(exist_ok=True);views=json.loads((d/'bedroom_doors130_matched_views.json').read_text());receipts=[];jobs=[];sections=[];pairs=[]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for folder in ['door130_baseline_cpu','door130_candidate_cpu']:
 p=d/folder;jobs.append(json.loads((p/'job.json').read_text()) if (p/'job.json').exists() else {});q=p/'candidate/render_receipt.json';a=json.loads(q.read_text()) if q.exists() else None
 if a:assert sha(a['source'])==a['source_sha256']
 receipts.append(a)
for i,v in enumerate(views):
 fs=[next((f for f in (a or {}).get('frames',[]) if f['name']==v['name']),None) for a in receipts];cells=[]
 for label,f in zip(['A129','B130'],fs):
  body='<p>CPU 렌더 진행 · 완료 영수증 대기</p>'
  if f:
   src=Path(f['path']);assert sha(src)==f['sha256'];jpg=out/(label+'_'+v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1400,1050));im.save(jpg,quality=89);body='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+jpg.name+'"></a>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 if all(fs):
  for k in ['camera','width','height','samples']:assert fs[0][k]==fs[1][k]
  for k in ['device','renderer_sha256','lighting_policy','lighting_overrides','render_threads','denoising']:assert receipts[0][k]==receipts[1][k]
  pairs.append({'name':v['name'],'baseline':fs[0],'candidate':fs[1]})
 sections.append('<section id="v'+str(i)+'"'+(' hidden' if i else '')+'><h2>'+html.escape(v['name'])+'</h2><div class="pair">'+''.join(cells)+'</div></section>')
(out/'evidence.json').write_text(json.dumps({'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'required_pairs':2,'completed_pairs':len(pairs),'pairs':pairs,'jobs':jobs,'direct_visual_review_complete':(out/'visual_review.json').exists(),'independent_visual_review_complete':(out/'independent_coverage_verified.json').exists(),'accepted':False,'scope':'Same cameras1280px48samples CPU4. Native bedroom2 single-leaf doors replace oversized double-door assemblies; frame fitted to measured openings; source129 furniture/lighting retained. No whole-room reference or photo acceptance.'},indent=2))
page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>주거130 침실2 출입</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}button{padding:10px;margin:4px}section[hidden]{display:none}</style><h1>주거130 · 실제 native 단일문/침실2 출입</h1><p>A129/B130 동일카메라 '+str(len(pairs))+'/2쌍.CPU4·1280px·48샘플.직접 101·102 두 쌍 모두 확인:입구를 가리던 기존문을 개선해 침실이 보이고 금속 레버가 구분됩니다.기존 목재결이 과장되고 방/침구 표면은 균일해 실사성 미달입니다.직접 2/2쌍 검수 완료·독립검수 대기·전체 최종미승인.</p><p>두 실제 벽개구 폭0.911586m를 측정하고 원래0.82×2.30×0.045m 크기로 native Infinigen 단일문/레버를 생성했습니다.잘못된 약1.93m 양개문 어셈블리를 교체했고 원래 casing은 유지했습니다.원본 문짝/레버는 rigid hinge pose만 적용,frame 하단만 실제바닥에매입.문하부8mm·헤더roughgap3mm·양측roughgap5.79mm입니다.전체 가구나변기축소는 없습니다.</p><p>두600mm제안진입경로 실제메쉬/정점/바닥중심표본 충돌없음.연속문의회전/전체방운영/상층동선/전체품질 증명은 별도입니다.</p><p><a href="evidence.json">동일조건/원본</a> · <a href="../bedroom_doors130_build.json">native모델·치수·조립</a> · <a href="../bedroom2_129_actual_openings.json">실제벽개구</a> · <a href="../bedroom2_130_reserved_route_audit.json">실제경로</a> · <a href="../finalization/report.html">최종43뷰 검수</a></p><nav>'+''.join('<button data-tab="v'+str(i)+'">'+html.escape(v['name'])+'</button>' for i,v in enumerate(views))+'</nav>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>';assert len(page.encode())<30000;(out/'report.html').write_text(page);print('DOOR130_REPORT',len(pairs),len(page.encode()))
