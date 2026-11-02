"""Small native-nightstand A/B gallery, explicit contact/visual acceptance separation."""
from pathlib import Path
import json,html,hashlib,os
from PIL import Image
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=d/'bedroom111_review';out.mkdir(exist_ok=True);views=json.loads((d/'bedroom110_matched_views.json').read_text());figs=[];evidence=[];jobs={}
for label,folder in [('A','bedroom110_baseline_cpu'),('B','bedroom111_candidate_cpu')]:jobs[label]=json.loads((d/folder/'job.json').read_text())
for view in views:
 cells=[]
 for label,folder in [('A','bedroom110_baseline_cpu'),('B','bedroom111_candidate_cpu')]:
  src=d/folder/'candidate'/(view['name']+'.png')
  if src.exists():
   im=Image.open(src);im.load();im=im.convert('RGB');im.thumbnail((1200,1200));dst=out/(label+'_'+view['name']+'.jpg');im.save(dst,quality=88);evidence.append({'label':label,'path':str(src),'sha256':hashlib.sha256(src.read_bytes()).hexdigest()});body='<a href="'+html.escape(os.path.relpath(src,out))+'"><img src="'+dst.name+'" loading="lazy"></a>'
  else:body='<p>렌더 진행 중</p>'
  cells.append('<figure><figcaption>'+label+'</figcaption>'+body+'</figure>')
 figs.append('<details open><summary>'+view['name']+'</summary><div class="pair">'+''.join(cells)+'</div></details>')
(out/'evidence.json').write_text(json.dumps({'jobs':jobs,'images':evidence,'visual_review':'pending','accepted':False},indent=2))
page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>주거111 안방 협탁 A/B</title><style>body{font:16px/1.7 system-ui;max-width:1400px;margin:auto;padding:20px}.pair{display:flex}figure{width:50%;margin:5px}img{width:100%}</style><h1>주거111 · 102호 안방 협탁</h1><p>A=108, B=111 시험본. 원본 크기 타원형 제품2개로 단순 협탁 교체, 스탠드 높이만 상판 접촉에 맞춤. 같은 카메라·해상도·샘플·노출 정책. 스탠드 위치 변경에 따른 국소 광원 이동 가능성을 분리 기록하며 동일 조명장이라고 주장하지 않습니다. 직접·독립4장 검수 완료:두 시점 모두 후보 선호, 국소 제조 디테일 개선. 밋밋한 금속/흰 상판·미해결 침구/외부환경으로 전체합격 아님. 데이터셋 승격 없음.</p><p><a href="blind_visual_review.json">독립 비평</a> · <a href="visual_review.json">직접 비평</a> · <a href="matched_AB_contract.json">비교 조건</a> · <a href="evidence.json">렌더 상태·이미지 근거</a> · <a href="../bedroom110_build.json">제품 배치</a> · <a href="../bedroom111_lamp_support_audit.json">실제 상판 접촉 검사</a> · <a href="../bedroom110_studio_cpu/visual_review.json">제품 스튜디오 비평</a></p>'''+''.join(figs)+'</html>';assert len(page.encode())<20000;(out/'report.html').write_text(page);print(out/'report.html')
