"""Mixed receipt sources, same120 baseline source, matched room comparisons with no acceptance inference."""
from pathlib import Path
import json,hashlib,html,os,datetime
from PIL import Image
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'core_traps121_review';out.mkdir(exist_ok=True);sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();views=json.loads((d/'core_traps121_views.json').read_text());q=d/'core_traps121_candidate_cpu/candidate/render_receipt.json';candidate=json.loads(q.read_text()) if q.exists() else None
if candidate:assert sha(candidate['source'])==candidate['source_sha256']
pairs=[];sections=[];baseline_hashes=set()
for i,v in enumerate(views):
 folder='core_traps121_baseline_oblique_cpu' if 'oblique' in v['name'] else 'threshold120_candidate_cpu';p=d/folder/'candidate/render_receipt.json';baseline=json.loads(p.read_text()) if p.exists() else None
 if baseline:assert sha(baseline['source'])==baseline['source_sha256'];baseline_hashes.add(baseline['source_sha256'])
 frames=[next((f for f in (a or {}).get('frames',[]) if f['name']==v['name']),None) for a in [baseline,candidate]];cells=[]
 if baseline and candidate:
  for k in ['device','lighting_policy','lighting_overrides','denoising','renderer_sha256','render_threads']:assert baseline[k]==candidate[k],k
 if all(frames):
  for k in ['camera','width','height','samples']:assert frames[0][k]==frames[1][k],(v['name'],k)
  pairs.append({'name':v['name'],'baseline':frames[0],'candidate':frames[1]})
 for label,f in zip(['A120','B121'],frames):
  if f:
   src=Path(f['path']);assert sha(src)==f['sha256'];jpg=out/(label+'_'+v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1400,1400));im.save(jpg,quality=89);body='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+jpg.name+'"></a>'
  else:body='<p>렌더 대기</p>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 sections.append('<section id="v'+str(i)+'"'+(' hidden' if i else '')+'><h2>'+html.escape(v['name'])+'</h2><div class="pair">'+''.join(cells)+'</div></section>')
assert len(baseline_hashes)<=1;(out/'matched_AB_contract.json').write_text(json.dumps({'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'required_pairs':4,'completed_pairs':len(pairs),'baseline_source_hashes':list(baseline_hashes),'candidate_source_sha256':candidate.get('source_sha256') if candidate else None,'same_camera_resolution_samples_renderer_lighting_policy_cpu_threads':True,'pairs':pairs,'accepted':False},indent=2));blind='<a href="blind_visual_review.json">독립 원본8장 비평</a> · ' if (out/'blind_visual_review.json').exists() else '독립 검수 대기 · ';page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>주거121 실제 배수관 방 시험</title><style>body{font:16px/1.7 system-ui;max-width:1450px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}button{padding:12px;margin:5px}section[hidden]{display:none}</style><h1>주거121 · 두 코어 변기 배수관 방 시험</h1><p>A120/B121 비교 '+str(len(pairs))+'/4쌍 완료. 두 코어 변기에 실제 폐곡면 배수관이 연결된 native 파생 메쉬를 시험했습니다. 상부 좌표·실제 폭/깊이/높이·좌판 높이0.410m·배치/스케일·방의 재질 슬롯을 유지했습니다. 물 표면·불투명 덮개·카메라별 가림을 추가하지 않았습니다.</p><p>직접·독립 원본8장 검수 완료: 위쪽2쌍은 B선호, 사선2쌍은 가림으로 동률입니다. 타원 이음선·건조한 내부가 남아 실사성은 미달입니다. 나머지8개 변기는 원래 메쉬 그대로이며 전체 욕실/배관/동선/실사성 합격이 아닙니다.</p><p>경로 검사도 객체 이름 목록을 버리고 렌더 레이어 기준 전체2254메쉬를 분류했습니다.2049개 포함·205개 제외의 이유를 기록하고 실제 평가 삼각형과 면에 쓰인 정점으로 두 코어 경로를 검사했습니다. 인스턴스·렌더 시점 변위·텍스처 투명도·전체 층 동선은 별도 미검증입니다.</p><p>'+blind+'<a href="matched_AB_contract.json">동일조건·원본 해시</a> · <a href="../core_traps121_build.json">실제 메쉬 교체</a> · <a href="../core_traps121_saved_audit.json">저장본 크기/좌판/배수관/지지</a> · <a href="../core121_all_render_mesh_route_audit.json">전체 렌더 메쉬 경로 검사</a> · <a href="../core121_render_mesh_inventory.json">포함·제외 전체 목록</a></p><nav>'+''.join('<button data-tab="v'+str(i)+'">'+('101' if i%2==0 else '102')+(' 사선' if i>1 else ' 위쪽')+'</button>' for i in range(4))+'</nav>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>';assert len(page.encode())<30000;(out/'report.html').write_text(page);print('CORE121_MATCHED_REPORT',len(pairs),4)
