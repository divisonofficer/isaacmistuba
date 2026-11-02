"""Receipt-bound partial/full A/B gallery; does not infer visual acceptance."""
from pathlib import Path
import json,hashlib,html,os,datetime
from PIL import Image
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';out=d/'glazing114_review';out.mkdir(exist_ok=True);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();names=[v['name'] for v in json.loads((d/'glazing114_matched_views.json').read_text())];receipts=[]
for folder in ['glazing114_baseline_cpu','glazing114_candidate_cpu']:
 p=d/folder/'candidate/render_receipt.json';a=json.loads(p.read_text()) if p.exists() else None
 if a:assert sha(Path(a['source']))==a['source_sha256']
 receipts.append(a)
a,b=receipts
if a and b:
 for k in ['device','lighting_policy','denoising','renderer_sha256']:assert a[k]==b[k],k
pairs=[];sections=[]
for i,name in enumerate(names):
 frames=[next((f for f in (z or {}).get('frames',[]) if f['name']==name),None) for z in receipts];cells=[]
 if all(frames):
  for k in ['camera','width','height','samples']:assert frames[0][k]==frames[1][k],(name,k)
  pairs.append({'name':name,'baseline':frames[0],'candidate':frames[1]})
 for label,f in zip(['A r113','B r114'],frames):
  if f:
   src=Path(f['path']);assert sha(src)==f['sha256'];dst=out/(label[0]+'_'+name+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1400,1400));im.save(dst,quality=88);cell='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+dst.name+'"></a>'
  else:cell='<p>렌더 대기</p>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+cell+'</figure>')
 sections.append('<section id="v'+str(i)+'"'+(' hidden' if i else '')+'><h2>'+name+'</h2><div class="pair">'+''.join(cells)+'</div></section>')
contract={'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'required_pairs':6,'completed_pairs':len(pairs),'pairs':pairs,'source_hashes':[z['source_sha256'] if z else None for z in receipts],'comparison_scope':'Same camera/resolution/samples/AgX exposure0/CPU/renderer policy. Different thread counts6vs4. Six old portal areas removed in B as part of aperture replacement; this is NOT a materials-only or same-light-field experiment.','lighting_overrides':[z['lighting_overrides'] if z else None for z in receipts],'accepted':False};(out/'matched_AB_contract.json').write_text(json.dumps(contract,indent=2))
page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>사무실114 통창 비교</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}button{padding:10px;margin:5px}section[hidden]{display:none}</style><h1>사무실114 · 개별실 통창 시험</h1><p>미승인 후보. 비교 렌더 완료 '+str(len(pairs))+'/6쌍. 6개 원본 창호2.145×0.22×2.395m, 유리8mm, 원본 스케일 유지. 기존 창과 보조광원 제거를 포함한 개구부 시험이며 동일 광장 실험은 아닙니다.</p><p>저장본 수정자 평가면에서 유리 구간288개 광선 차폐0, 창틀 경계192개 표본 누락0. 표본 검사는 접합부 전체·실링·구조 지지·동선의 합격이 아닙니다. 실제 렌더에서 창 규모는 개선되지만 가까운 콘크리트 외벽과 빈 실내가 여전히 레퍼런스와 다릅니다. 후보6장·레퍼런스1장 및 A/B12장 독립 검수 완료:6쌍 모두 B 선호,전체 주요 수정은 필요합니다. 전체 사무실 최신본 검수는 아직 완료 전입니다.</p><p><a href="blind_AB_review.json">A/B12장 독립 비평</a> · <a href="blind_candidate_review.json">후보6장·참조 독립 비평</a> · <a href="matched_AB_contract.json">조건·소스·원본 해시</a> · <a href="../glazing114_evaluated_fit_audit.json">평가면 검사</a> · <a href="../glazing114_build.json">수정 기록</a> · <a href="../fine_current.html">종합</a></p><nav>'+''.join('<button data-tab="v'+str(i)+'">'+html.escape(n)+'</button>' for i,n in enumerate(names))+'</nav>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>';assert len(page.encode())<30000;(out/'report.html').write_text(page);print('GLAZING114_PAIRED_REPORT',len(pairs),6)
