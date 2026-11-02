"""Small pending/completed image gallery, never infer visual acceptance."""
from pathlib import Path
import json,html,hashlib
from PIL import Image
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';out=d/'taskchairs112_review';out.mkdir(exist_ok=True)
views=json.loads((d/'taskchairs112_matched_views.json').read_text());sections=[];states={};images=[]
for key in ['baseline','candidate']:
 p=d/f'taskchairs112_{key}_cpu';states[key]=json.loads((p/'job.json').read_text())
for i,v in enumerate(views):
 figs=[]
 for label,key in [('A','baseline'),('B','candidate')]:
  src=d/f'taskchairs112_{key}_cpu'/'candidate'/(v['name']+'.png')
  if src.exists():
   dst=out/(label+'_'+v['name']+'.jpg');im=Image.open(src);im.load();im=im.convert('RGB');im.thumbnail((1400,1400));im.save(dst,quality=88);images.append({'label':label,'view':v['name'],'source':str(src),'sha256':hashlib.sha256(src.read_bytes()).hexdigest()});body='<a href="'+html.escape('../'+str(src.relative_to(d)))+'"><img loading="lazy" src="'+dst.name+'"></a>'
  else:body='<p>렌더 대기 / 진행 중</p>'
  figs.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 sections.append('<section id="v'+str(i)+'"'+(' hidden' if i else '')+'><h2>'+html.escape(v['name'])+'</h2><div class="pair">'+''.join(figs)+'</div></section>')
manifest={'render_states':states,'images':images,'visual_review':'pending','accepted':False};(out/'evidence.json').write_text(json.dumps(manifest,indent=2))
page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>사무실112 작업 의자 A/B</title><style>body{font:16px/1.6 system-ui;max-width:1500px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}button{padding:12px;margin:5px}section[hidden]{display:none}</style><h1>사무실112 · 작업 의자24개 교체</h1><p>A=r111, B=r112. 실제 B06W5XBL3D 제품 원본 크기·UV 유지. 차콜색이므로 파란 레퍼런스 색상은 미해결입니다. 기하 검사 통과는 실사성 합격을 의미하지 않습니다. 직접 전후8장 검수 완료: 제조 디테일 국소개선, 파란 메쉬 레퍼런스와 스타일 차이·균일한 원단/플라스틱 미해결. 독립 검수8장 완료: 네 시점 모두 후보 선호, 국소 개선만 인정, 전체 승인 및 데이터셋 승격 없음.</p><p><a href="blind_visual_review.json">독립 검수</a> · <a href="visual_review_partial.json">직접 비평</a> · <a href="matched_AB_contract.json">동일 조건 검증</a> · <a href="evidence.json">진행 상태·이미지 해시</a> · <a href="../taskchairs112_saved_audit.json">저장 메쉬/UV 검사</a> · <a href="../taskchairs112_build.json">배치 및 제한된 충돌 검사</a></p><nav>'''+''.join('<button data-tab="v'+str(i)+'">'+html.escape(v['name'])+'</button>' for i,v in enumerate(views))+'</nav>'+''.join(sections)+'''<script>for(const b of document.querySelectorAll('[data-tab]'))b.onclick=()=>{for(const s of document.querySelectorAll('section'))s.hidden=s.id!==b.dataset.tab;};</script></html>'''
assert len(page.encode())<30000;(out/'report.html').write_text(page);print(out/'report.html')
