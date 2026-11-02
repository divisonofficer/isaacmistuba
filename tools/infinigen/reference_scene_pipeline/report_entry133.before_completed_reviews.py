"""Local source-bound bathroom130/131 A/B; never replaces pinned130 full review."""
from pathlib import Path
from PIL import Image
import json,html,hashlib,os,datetime
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=D/'entry133_review';out.mkdir(exist_ok=True);esc=lambda s:html.escape(str(s));sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();build=json.loads((D/'entry_batch133_build.json').read_text());views=json.loads((D/'entry_batch133_matched_views.json').read_text());receipts=[];jobs=[];pairs=[];sections=[]
for folder in ['entry133_baseline_cpu','entry133_candidate_cpu']:
 p=D/folder;q=p/'candidate/render_receipt.json';a=json.loads(q.read_text()) if q.exists() else {};jobs.append(json.loads((p/'job.json').read_text()) if (p/'job.json').exists() else {})
 if a:assert sha(a['source'])==a['source_sha256']
 receipts.append(a)
for v in views:
 fs=[next((f for f in a.get('frames',[]) if f['name']==v['name']),None) for a in receipts];cells=[]
 for label,f in zip(['A132','B133'],fs):
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
for name in ['entry133_reserved_route_audit.json','entry133_sampled_sweeps.json']:
 p=D/name
 if p.exists():
  a=json.loads(p.read_text());value=next((a[k] for k in ['sampled_surface_intersections_clear','both_proposed_entry133_routes_clear_in_tested_scope'] if k in a),'unknown');checks.append('<li><a href="../'+name+'">'+esc(name)+'</a>: '+esc(value)+'</li>')
 else:checks.append('<li>'+esc(name)+' · 측정 중</li>')
evidence={'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source':build['source'],'candidate':build['candidate'],'completed_pairs':len(pairs),'required_pairs':2,'pairs':pairs,'jobs':jobs,'direct_visual_review_complete':(out/'visual_review.json').exists(),'independent_visual_review_complete':(out/'independent_coverage_verified.json').exists(),'accepted':False,'scope':'Two measured102 bedroom3/foyer-west native door assemblies only. Original820mm leaf/lever and826mm clear fixed frame,3mm jamb gap, fixedframe+rigid100deg leaf. Other geometry/materials/light unchanged. Full130 review remains separate.'};(out/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
intro='<h2>102호 침실3·서쪽 현관문</h2><p>A132/B133 '+str(len(pairs))+'/2쌍 · 동일 카메라1280px·48샘플·CPU2·AgX 노출0. 렌더 진행 중·직접/독립 RGB 검수 전·최종 미승인.</p><p>실제91.16cm 개구 두 곳을 확인하고 잘못 배치된 GlassPanel 문과 폭193cm 양개문 어셈블리를 각각82cm 원래 단일문·레버/82.6cm clear native 문틀로 교체했습니다. 측면3mm, 하단8mm, rough 상단3mm. 기존 casing·가구·위생기구·재질·조명은 보존했습니다.</p><p>두600mm 진입 경로와 문별41개0~100도 자세의 실제 삼각형 표면 교차 검사를 통과했습니다. 경로는 각 개구의 국소 진입에만 해당하며 전체 연결·연속 회전체적·법규 인증은 아닙니다. 101 작은 욕실의 문·위생기구 문제도 별도 미해결입니다.</p><ul>'+''.join(checks)+'</ul><p><a href="../entry_batch133_build.json">제작·원본 보존·치수·해시</a> · <a href="evidence.json">동일조건/실제 렌더</a> · <a href="../portal132_review/report.html">직접 측정한 문제·수정 대상</a> · <a href="../bathroom_door132_review/report.html">앞선132 욕실 문 검수</a> · <a href="../finalization/report.html">고정130 전체43뷰</a></p>'
page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>주거133 두 출입문 교정</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:6px}img{width:100%}button{padding:12px;margin:4px}section[hidden]{display:none}</style><h1>주거133 · 두 출입문 교정 후보</h1><nav><button data-tab="summary">현재·실측</button>'+''.join('<button data-tab="'+esc(v['name'])+'">'+esc(v['name'])+'</button>' for v in views)+'</nav><section id="summary">'+intro+'</section>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>'
assert len(page.encode())<25000;(out/'report.html').write_text(page);print('ENTRY133_REPORT',len(pairs),len(page.encode()))
