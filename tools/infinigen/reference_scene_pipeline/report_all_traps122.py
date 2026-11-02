"""Receipt-backed ten-fixture gallery, eight changed matched pairs, never accepts by audit."""
from pathlib import Path
import json,hashlib,html,os,datetime
from PIL import Image
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'all_traps122_review';out.mkdir(exist_ok=True);sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();build=json.loads((d/'all_traps122_build.json').read_text());views=json.loads((d/'all_traps122_views.json').read_text());changed={x['key'] for x in build['replaced']};receipts=[]
for folder in ['all_traps122_baseline_cpu','all_traps122_candidate_cpu']:
 p=d/folder/'candidate/render_receipt.json';a=json.loads(p.read_text()) if p.exists() else None
 if a:assert sha(a['source'])==a['source_sha256']
 receipts.append(a)
sections=[];pairs=[];counts=[len((a or {}).get('frames',[])) for a in receipts]
for i,v in enumerate(views):
 cells=[];frames=[next((f for f in (a or {}).get('frames',[]) if f['name']==v['name']),None) for a in receipts];key=v['name'][6:]
 for label,f in zip(['A121','B122'],frames):
  body='<p>같은 메쉬 유지 · 기준 렌더 대상 아님</p>' if label=='A121' and key not in changed else '<p>렌더 진행·원본 미완료</p>'
  if f:
   src=Path(f['path']);assert sha(src)==f['sha256'];p=out/(label+'_'+v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1000,750));im.save(p,quality=89);body='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+p.name+'"></a>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 if all(frames):
  for k in ['camera','width','height','samples']:assert frames[0][k]==frames[1][k]
  for k in ['device','renderer_sha256','lighting_policy','lighting_overrides','render_threads','denoising']:assert receipts[0][k]==receipts[1][k]
  pairs.append({'key':key,'baseline':frames[0],'candidate':frames[1]})
 sections.append('<section id="v'+str(i)+'"'+(' hidden' if i else '')+'><h2>'+html.escape(key)+'</h2><div class="pair">'+''.join(cells)+'</div></section>')
proof={'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'candidate_source_sha256':build['candidate_sha256'],'baseline_frames_complete':counts[0],'candidate_frames_complete':counts[1],'required_candidate_frames':10,'required_matched_pairs':8,'complete_matched_pairs':len(pairs),'pairs':pairs,'visual_review_complete':(out/'independent_coverage_verified.json').exists(),'accepted':False,'scope':'768px/32sample diagnostic preflight, not microtexture or final full-suite acceptance. Two unchanged core products have no newly requested baseline images.'};(out/'evidence.json').write_text(json.dumps(proof,indent=2));page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>주거122 변기10개</title><style>body{font:16px/1.7 system-ui;max-width:1400px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}button{padding:10px;margin:4px}section[hidden]{display:none}</style><h1>주거122 · 변기10개 확대 시험</h1><p>후보 '+str(counts[1])+'/10장, 변경된8개 기준 '+str(counts[0])+'/8장, 동일조건 비교 '+str(len(pairs))+'/8쌍. 직접·독립 원본18장 검수 완료:변경8쌍 B선호. 도기 이음선·물 표현·전체 실사성 미달. 두 코어 변기는121과 같은 메쉬이며 나머지8개만 교체했습니다.</p><p>저장본10개 메쉬·좌판0.410m·바닥90표본 확인. 크기/배치/재질슬롯 유지. 전체 동선·문 회전·물 표현·도기 이음선·실사성은 미검증/미해결이며 합격 근거가 아닙니다.768px 진단 뷰는 고주파 재질 판정용이 아닙니다.</p><p><a href="../fine_current.html">현재 현황</a> · <a href="../all_traps122_build.json">실제 빌드</a> · <a href="../all_traps122_saved_audit.json">저장본 검사 범위</a> · <a href="blind_visual_review.json">독립 원본18장 비평</a> · <a href="visual_review.json">직접 비평</a> · <a href="evidence.json">원본/비교 조건</a> · <a href="../core_traps121_review/report.html">이전121 독립검수</a></p><nav>'+''.join('<button data-tab="v'+str(i)+'">'+html.escape(v['name'][6:])+'</button>' for i,v in enumerate(views))+'</nav>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>';assert len(page.encode())<30000;(out/'report.html').write_text(page);print('ALL122_REPORT',counts,len(pairs))
