"""Three-way optical diagnostic; wrong parameters are not visual acceptance."""
from pathlib import Path
import json,hashlib,os,datetime
from PIL import Image
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'curtain_ior_trial';views=json.loads((out/'views.json').read_text());labels=['A native M1/IOR0','B M0/IOR0 (held)','C M0/IOR1.46'];folders=['curtain120_studio_cpu','curtain_dielectric_candidate_cpu','curtain_ior_candidate_cpu'];receipts=[];sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for folder in folders:
 p=d/folder/'candidate/render_receipt.json';a=json.loads(p.read_text()) if p.exists() else None
 if a:assert sha(a['source'])==a['source_sha256']
 receipts.append(a)
sections=[];groups=[]
for i,v in enumerate(views):
 frames=[next((f for f in (a or {}).get('frames',[]) if f['name']==v['name']),None) for a in receipts];cells=[]
 if all(frames):
  for k in ['camera','width','height','samples']:assert all(f[k]==frames[0][k] for f in frames)
  for k in ['device','renderer_sha256','lighting_policy','lighting_overrides','render_threads','denoising']:assert all(a[k]==receipts[0][k] for a in receipts)
  groups.append({'name':v['name'],'frames':frames})
 for j,(label,f) in enumerate(zip(labels,frames)):
  body='<p>렌더 진행</p>'
  if f:
   src=Path(f['path']);assert sha(src)==f['sha256'];jpg=out/(str(j)+'_'+v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1000,750));im.save(jpg,quality=89);body='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+jpg.name+'"></a>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 sections.append('<section id="v'+str(i)+'"'+(' hidden' if i else '')+'><div class="pair">'+''.join(cells)+'</div></section>')
proof={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'required_comparisons':3,'completed_comparisons':len(groups),'groups':groups,'accepted':False,'scope':'Optical constants inferred, not measured; geometry/maps/lighting/cameras unchanged. B retains IOR0 and is held. No room integration or textile manufacturing acceptance.'};(out/'matched_ABC_contract.json').write_text(json.dumps(proof,indent=2));review=json.loads((out/'visual_review.json').read_text()) if (out/'visual_review.json').exists() else None;summary=review.get('summary') if review else 'A/B 원본6장 직접 확인: B는 크림색·주름 대비가 약해졌으며 IOR0 잔존으로 미채택. C 직접 검수 전.';page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>커튼 광학 원인 분리</title><style>body{font:16px/1.7 system-ui;max-width:1500px;margin:auto;padding:20px}.pair{display:flex}figure{width:33%;margin:5px}img{width:100%}button{padding:12px;margin:5px}section[hidden]{display:none}</style><h1>커튼 · 비금속/IOR 원인 분리</h1><p>동일조건 비교 '+str(len(groups))+'/3시점. '+summary+'</p><p>원본은 Metallic1·IOR0. B는 Metallic만0으로 수정했지만 잘못된 IOR을 남겨 보류했습니다. C는 IOR1.46 추정값까지 수정한 별도 후보입니다. 원본·실패 후보를 보존하며 실사성 합격이나 방 적용은 아닙니다.</p><p><a href="matched_ABC_contract.json">카메라/광원/원본 해시</a> · <a href="blind_visual_review.json">독립 원본9장 검수: A/C 동률</a> · <a href="build.json">C 변경</a> · <a href="import_preflight_evidence.json">실제 원본 재수입 광학 검사</a> · <a href="../curtain120_products/report.html">native 형상 검수</a> · <a href="../fine_current.html">현재 씬</a></p><nav>'+''.join('<button data-tab="v'+str(i)+'">'+label+'</button>' for i,label in enumerate(['앞','뒤','상단 근접']))+'</nav>'+''.join(sections)+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script></html>';assert len(page.encode())<30000;(out/'report.html').write_text(page);print('CURTAIN_OPTICAL_REPORT',len(groups),3)
