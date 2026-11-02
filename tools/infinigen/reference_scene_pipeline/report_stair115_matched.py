"""Small exterior-boundary repair gallery; incomplete frames explicitly pending."""
import json,hashlib,html,os
from pathlib import Path
from PIL import Image
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'stair115_review';out.mkdir(exist_ok=True);figs=[];frames=[]
for name in ['stairs','stairs112_upper_landing']:
 cells=[]
 for label,folder in [('A','stair112_baseline_cpu'),('B','stair115_candidate_cpu')]:
  src=d/folder/'candidate'/(name+'.png')
  if src.exists():
   im=Image.open(src);im.load();im=im.convert('RGB');im.thumbnail((1200,1200));dst=out/(label+'_'+name+'.jpg');im.save(dst,quality=88);frames.append({'label':label,'path':str(src.resolve()),'sha256':hashlib.sha256(src.read_bytes()).hexdigest()});body='<a href="'+os.path.relpath(src,out)+'"><img loading="lazy" src="'+dst.name+'"></a>'
  else:body='<p>렌더 진행 중</p>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 figs.append('<details open><summary>'+name+'</summary><div class="pair">'+''.join(cells)+'</div></details>')
(out/'evidence.json').write_text(json.dumps({'frames':frames,'accepted':False,'visual_review':'pending'},indent=2))
page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>주거115 계단 연결 A/B</title><style>body{font:16px/1.7 system-ui;max-width:1400px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}</style><h1>계단115 · 계단참 난간 보완</h1><p>A=108, B=115 시험. 콘크리트 닫힌 챌판, 실제 지지면 안쪽으로 이동한 난간, 깊이1.1m 상부 계단참과 벽·원본 문을 추가했습니다. 위층 출입 경계는 제공된 평면에 없는 추정 설계입니다. 직접·독립 전후4장 검수에서 두 시점 후보 선호. 수평 난간과 곡선 손잡이 연결을 추가했으며 균일한 콘크리트·벽 이음선·앵커 디테일과 전체동선 검증은 남았습니다. 승인·승격되지 않았습니다.</p><p><a href="blind_visual_review.json">독립 비평</a> · <a href="visual_review.json">직접 비평</a> · <a href="matched_AB_contract.json">비교 조건</a> · <a href="../stair115_landing_guard.json">새 난간 지지·연결 검사</a> · <a href="../stair114_saved_audit.json">저장본 기하 검사</a> · <a href="../stair114_upper_connection.json">추정설계 범위</a> · <a href="evidence.json">이미지 근거</a> · <a href="../stair112_review/report.html">이전 실패 비평</a></p>'''+''.join(figs)+'</html>';assert len(page.encode())<20000;(out/'report.html').write_text(page);print(out/'report.html')
