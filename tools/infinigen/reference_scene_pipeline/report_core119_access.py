"""Small source-bound access trial report; visual acceptance never inferred from geometry."""
from pathlib import Path
import json,hashlib,html,os,datetime
from PIL import Image
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'core119_access_review';out.mkdir(exist_ok=True);views=json.loads((d/'threshold118_matched_views.json').read_text());folders=[d/'threshold118_baseline_cpu',d/'threshold119_candidate_cpu'];receipts=[]
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
 for label,f in zip(['A r116','B r119'],frames):
  if f:
   src=Path(f['path']);assert hashlib.sha256(src.read_bytes()).hexdigest()==f['sha256'];dst=out/(label[0]+'_'+v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1300,1300));im.save(dst,quality=88);body='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+dst.name+'"></a>'
  else:body='<p>렌더 진행 중 · 시각 판정 전</p>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 sections.append('<section id="v'+str(i)+'" hidden><h2>'+html.escape(v['name'])+'</h2><div class="pair">'+''.join(cells)+'</div></section>')
for k in ['device','lighting_policy','lighting_overrides','denoising','renderer_sha256']:
 if all(receipts):assert receipts[0][k]==receipts[1][k]
(out/'matched_AB_contract.json').write_text(json.dumps({'pairs':pairs,'required_pairs':4,'completed_pairs':len(pairs),'comparison_scope':'Same CPU camera/resolution/samples/renderer lighting policy, AgX exposure0. Frames source/hash verified as available.','visual_review_complete':False,'accepted':False},indent=2));route=json.loads((d/'core119_route_volume_audit.json').read_text());floor=json.loads((d/'core119_fullwidth_floor_audit.json').read_text());ann=json.loads((d/'room_annotation_candidate_r119_evidence.json').read_text());alignment=json.loads((d/'casing119_alignment_build.json').read_text());sweep=d/'core119_native_door_sweep_audit.json';motions=json.loads(sweep.read_text()) if sweep.exists() else None
current='<p>미승인 후보119. 실제 문틀 중심 오차를101호 '+f'{alignment["rows"][0]["translation_y_m"]:.3f}m,102호 {alignment["rows"][1]["translation_y_m"]:.3f}m'+' 바로잡았습니다. 문 통과부 마감 바닥2개를 연결하고, 고정 문틀 하단을 바닥 아래로 설치했으며, 두 문 중앙의 고립된1mm 큐브를 제거했습니다. 문짝/손잡이는 원본 위치를 유지했습니다.</p><p>확장 검사에서 실제 걸레받이가 두 출입구를 가로질러 충돌합니다. 앞선 벽·문틀·문짝·설비 부분집합 검사 통과는 걸레받이 누락으로 철회했습니다. 실제 바닥 면의 전폭 미지지 면적0m²와 출입 장애물 없음은 별개입니다. 근접 A/B에서도 큰 홈 형태가 남아119는 시각/출입 미달입니다.120에서 해당 걸레받이를 국소 절단 중입니다. 이 검사는 나머지8개 화장실·층 전체 동선·법규·구조 지지의 합격이 아닙니다.</p><p>기존116에서 표면 교차가 확인된 상태와117/118 중간 후보도 보존했습니다. 실제 바닥 대신 비표시 portal cutter를 바닥 지지로 계산하지 않았습니다. 원본 point-only 관절 메타데이터는 물리 표면의 정점으로 계산하지 않습니다.</p><p>후보 방 매핑은 실제 벽/여닫이문과 변기10개를 연결했습니다. 정식 매핑/데이터셋에는 아직 반영하지 않았습니다. A/B4쌍 중 '+str(len(pairs))+'쌍 완료, 직접·독립 시각 검수 전, 전체 실사성/동선 미달·승격 없음.</p><p><a href="../core119_route_volume_audit.json">실제3D 경로</a> · <a href="../core119_fullwidth_floor_audit.json">실제 바닥 전폭</a> · <a href="../core119_native_door_sweep_audit.json">문 회전 표본/보수적 설비 외곽</a> · <a href="../room_annotation_candidate_r119_evidence.json">10방 후보 매핑 근거</a> · <a href="../room_mapping_candidate_r119.json">후보 매핑</a> · <a href="../casing119_alignment_build.json">문틀 정렬</a> · <a href="../frame118_installation_build.json">문틀 하단 설치</a> · <a href="../threshold117_build.json">바닥 연결</a> · <a href="matched_AB_contract.json">A/B 원본 조건</a></p>'
page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>주거119 코어 출입 검수</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}button{padding:10px;margin:5px}section[hidden]{display:none}</style><h1>주거119 · 코어 화장실2곳 출입 수정</h1><nav><button data-tab="current">수정·검사·한계</button>'+''.join('<button data-tab="v'+str(i)+'">'+html.escape(v['name'])+'</button>' for i,v in enumerate(views))+'</nav><section id="current">'+current+'</section>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>';assert len(page.encode())<30000;(out/'report.html').write_text(page);print('CORE119_ACCESS_REPORT',len(pairs),4)
