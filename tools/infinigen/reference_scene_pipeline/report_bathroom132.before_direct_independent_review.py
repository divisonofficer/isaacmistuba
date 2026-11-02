"""Local source-bound bathroom130/131 A/B; never replaces pinned130 full review."""
from pathlib import Path
from PIL import Image
import json,html,hashlib,os,datetime
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=D/'bathroom_door132_review';out.mkdir(exist_ok=True);esc=lambda s:html.escape(str(s));sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();build=json.loads((D/'bathroom_door132_build.json').read_text());views=json.loads((D/'bathroom_door131_matched_views.json').read_text());receipts=[];jobs=[];pairs=[];sections=[]
for folder in ['bathroom_door131_baseline_cpu','bathroom_door132_candidate_cpu']:
 p=D/folder;q=p/'candidate/render_receipt.json';a=json.loads(q.read_text()) if q.exists() else {};jobs.append(json.loads((p/'job.json').read_text()) if (p/'job.json').exists() else {})
 if a:assert sha(a['source'])==a['source_sha256']
 receipts.append(a)
for v in views:
 fs=[next((f for f in a.get('frames',[]) if f['name']==v['name']),None) for a in receipts];cells=[]
 for label,f in zip(['A130','B132'],fs):
  body='<p>CPU 렌더 대기 · 아직 직접 시각검수 전</p>'
  if f:
   src=Path(f['path']);assert sha(src)==f['sha256'];jpg=out/(label+'_'+v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1280,960));im.save(jpg,quality=88);body='<a href="'+esc(os.path.relpath(src,out))+'"><img loading="lazy" src="'+jpg.name+'"></a>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 if all(fs):
  for k in ['camera','width','height','samples']:assert fs[0][k]==fs[1][k]
  for k in ['device','renderer_sha256','lighting_policy','lighting_overrides','render_threads','denoising']:assert receipts[0][k]==receipts[1][k]
  assert receipts[0]['source']==build['source'] and receipts[1]['source']==build['candidate']
  pairs.append({'name':v['name'],'baseline':fs[0],'candidate':fs[1]})
 sections.append('<section id="'+esc(v['name'])+'" hidden><h2>'+esc(v['name'])+'</h2><div class="pair">'+''.join(cells)+'</div></section>')
checks=[]
for name in ['bathroom2_130_actual_centre_entry_route_audit.json','bathroom2_132_actual_centre_entry_route_audit.json','bathroom132_sampled_sweep.json']:
 p=D/name
 if p.exists():
  a=json.loads(p.read_text());value=next((a[k] for k in ['sampled_surface_intersections_clear','proposed_bathroom101_entry_route_clear_in_tested_scope'] if k in a),'unknown');checks.append('<li><a href="../'+name+'">'+esc(name)+'</a>: '+esc(value)+'</li>')
 else:checks.append('<li>'+esc(name)+' · 측정 중</li>')
evidence={'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':build['source'],'candidate':build['candidate'],'completed_pairs':len(pairs),'required_pairs':2,'pairs':pairs,'jobs':jobs,'direct_visual_review_complete':(out/'visual_review.json').exists(),'independent_visual_review_complete':False,'accepted':False,'scope':'Local101 bathroom doorway only; pinned full130 review remains separate. Native leaf820x2300x45mm and826mm clear fixed frame; rigid outward100deg leaf+lever; other geometry/materials/light unchanged.'};(out/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
intro='<p><strong>r132 정지 중심 경로 및41개 자세 표면 교차검사 통과. 직접 RGB 검수와 독립검수 전으로 채택·승격하지 않았습니다.</strong></p><h2>101호 욕실 · native 단일문/레버</h2><p>A130/B132 '+str(len(pairs))+'/2쌍 · 동일 카메라1280px·48샘플·CPU2·AgX 노출0. 직접 시각검수 전·최종 미승인.</p><p>실제91.16cm 벽 개구에 설치된 양개문·큰 푸시바를82×230×4.5cm 원래 치수의 단일문·레버로 교체했습니다. 82.6cm clear native 문틀과82cm 원래 문짝을 조합해 측면3mm 조립 간격을 확보했습니다. 문짝 아래8mm·상단 개구3mm이며, 바깥으로100도 열었습니다. 문틀 고정, 가동부 rigid 회전, 다른 가구·변기·조명 불변.</p><p>이전131은 샤워부스/문틀 회전 충돌로 보류했습니다. 새132는 실제 개구 중심 y4.5712619m의 A/B 동일 경로와41개 회전 자세를 검사했습니다. 판정은 이 한 출입구의 정지 경로·이산 자세에만 해당합니다.</p><ul>'+''.join(checks)+'</ul><p>41개 자세의 삼각형 교차검사는 연속 회전 체적이나 건축 규정 인증이 아닙니다. 도기 내부·재질·욕실별 디자인·전체 동선 결함은 별도 미해결입니다.</p><p><a href="../bathroom_door131_build.json">치수·소스 해시</a> · <a href="../bathroom130_native_door_measurement.json">원래 잘못된 양개문·개구 실측</a> · <a href="evidence.json">동일조건/렌더 증거</a> · <a href="../finalization/bathroom_independent_review_r130.json">r130 독립 욕실 비평</a> · <a href="../finalization/report.html">고정 r130 전체43뷰 검수</a></p>'
page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>욕실132 바깥 열림 교정</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:6px}img{width:100%}button{padding:12px;margin:4px}section[hidden]{display:none}</style><h1>주거132 · 욕실 문 교정 후보</h1><nav><button data-tab="summary">현재·실측</button>'+''.join('<button data-tab="'+esc(v['name'])+'">'+esc(v['name'])+'</button>' for v in views)+'</nav><section id="summary">'+intro+'</section>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>'
assert len(page.encode())<25000;(out/'report.html').write_text(page);print('BATH132_REPORT',len(pairs),len(page.encode()))
