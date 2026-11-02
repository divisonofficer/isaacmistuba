"""Small source-bound access trial report; visual acceptance never inferred from geometry."""
from pathlib import Path
import json,hashlib,html,os,datetime
from PIL import Image
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'core120_access_review';out.mkdir(exist_ok=True);views=json.loads((d/'threshold118_matched_views.json').read_text());folders=[d/'threshold118_baseline_cpu',d/'threshold120_candidate_cpu'];receipts=[]
for p in folders:
 q=p/'candidate/render_receipt.json';a=json.loads(q.read_text()) if q.exists() else None
 if a:assert hashlib.sha256(Path(a['source']).read_bytes()).hexdigest()==a['source_sha256']
 receipts.append(a)
sections=[];pairs=[]
for i,v in enumerate(views):
 frames=[next((f for f in (a or {}).get('frames',[]) if f['name']==v['name']),None) for a in receipts];cells=[]
 if all(frames):
  for k in ['camera','width','height','samples']:assert frames[0][k]==frames[1][k]
  pairs.append({'baseline':frames[0],'candidate':frames[1]})
 for label,f in zip(['A r116','B r120'],frames):
  if f:
   src=Path(f['path']);assert hashlib.sha256(src.read_bytes()).hexdigest()==f['sha256'];dst=out/(label[0]+'_'+v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1300,1300));im.save(dst,quality=88);body='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+dst.name+'"></a>'
  else:body='<p>렌더 진행 중 · 시각 판정 전</p>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 sections.append('<section id="v'+str(i)+'" hidden><h2>'+html.escape(v['name'])+'</h2><div class="pair">'+''.join(cells)+'</div></section>')
for k in ['device','lighting_policy','lighting_overrides','denoising','renderer_sha256']:
 if all(receipts):assert receipts[0][k]==receipts[1][k]
(out/'matched_AB_contract.json').write_text(json.dumps({'pairs':pairs,'required_pairs':4,'completed_pairs':len(pairs),'comparison_scope':'Same CPU camera/resolution/samples/renderer lighting policy, AgX exposure0. Frames source/hash verified as available.','visual_review_complete':False,'accepted':False},indent=2));route=json.loads((d/'core120_route_volume_audit.json').read_text());floor=json.loads((d/'core120_fullwidth_floor_audit.json').read_text());ann=json.loads((d/'room_annotation_candidate_r119_evidence.json').read_text());alignment=json.loads((d/'casing119_alignment_build.json').read_text());sweep=d/'core120_native_door_sweep_audit.json';motions=json.loads(sweep.read_text()) if sweep.exists() else None
current='<p>미승인 후보120.119의 근접 렌더에서 흰 홈이 남아 실제 면을 추적했고, 출입구를 가로지르는 걸레받이가 원인으로 확인됐습니다.119의 부분집합 출입 통과 판정은 철회했습니다.</p><p>120은 실제 걸레받이 메쉬에서 두 현관 개구부에 해당하는 부분만 절단했습니다. 기존 바닥 연결·문틀 정렬·고정 하단 매립은 유지했습니다. 검사 대상에 실제 걸레받이를 추가한600mm×1.75m 경로 검사를 다시 수행했습니다. 나머지8개 화장실·층 전체 동선·정식 방 매핑/데이터셋 통합은 미검증입니다.</p><p>현재 A116/B120 비교 렌더 '+str(len(pairs))+'/4쌍 완료. 직접 원본8장 검수:횡단 걸레받이는 사라졌지만101 문틀 옆 얇은 절단 끝단과 양쪽 변기 배수구 바닥 노출은 남습니다.독립 원본8장 검수도 완료,B선호4/4의 국소 개선.실사성 합격/승격 없음. 기하검사만으로 문턱이 자연스럽게 보인다고 판정하지 않습니다.</p><p><a href="blind_visual_review.json">독립8장 비평</a> · <a href="visual_review.json">직접8장 비평</a> · <a href="../skirting120_portal_build.json">실제 걸레받이 국소 절단</a> · <a href="../core120_route_volume_audit.json">걸레받이 포함 실제 경로</a> · <a href="../core120_fullwidth_floor_audit.json">현재 소스 전폭 바닥</a> · <a href="../core120_native_door_sweep_audit.json">걸레받이 포함 문 회전</a> · <a href="../core119_access_review/report.html">119 판정 철회/반례</a> · <a href="matched_AB_contract.json">A/B 조건·원본 해시</a></p>'
page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>주거120 코어 출입 검수</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}button{padding:10px;margin:5px}section[hidden]{display:none}</style><h1>주거120 · 실제 걸레받이 반례 수정</h1><nav><button data-tab="current">수정·검사·한계</button>'+''.join('<button data-tab="v'+str(i)+'">'+html.escape(v['name'])+'</button>' for i,v in enumerate(views))+'</nav><section id="current">'+current+'</section>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>';assert len(page.encode())<30000;(out/'report.html').write_text(page);print('CORE120_ACCESS_REPORT',len(pairs),4)
