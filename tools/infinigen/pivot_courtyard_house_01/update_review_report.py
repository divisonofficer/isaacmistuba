"""Render explicit, human-reviewed round evidence into the project HTML report."""
import json,html,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
base=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
if 'TABBED_PROGRESS_V1' in (base/'progress.html').read_text():
 import runpy
 runpy.run_path(str(Path(__file__).with_name('build_progress_dashboard.py')),run_name='__main__')
 raise SystemExit(0)
doc=json.loads((base/'iteration_reviews.json').read_text())
esc=lambda x:html.escape(str(x))
parts=['<!-- ITERATION_REVIEWS_START --><section id="iteration-reviews"><h2>라운드별 직접 시각 검수</h2><p>동일 카메라의 전후 렌더를 비교합니다. 유사도는 구조·가구·재질·조명을 나눠 판단한 정성 평가이며 계산된 유사도 점수가 아닙니다. 평면도는 공간 연결의 기준, 생성 레퍼런스는 스타일의 기준입니다.</p>']
for r in reversed(doc['rounds']):
 parts.append('<details '+('open' if r is doc['rounds'][-1] else '')+'><summary>'+esc(r['round'])+' · '+esc(r['status'])+'</summary><article><h3>'+esc(r['round'])+'</h3><p>'+esc(r['summary'])+'</p><p>실행: '+esc(r['render_settings'])+'</p>')
 if r.get('scene'):parts.append('<p><a href="'+esc(r['scene'])+'">이 라운드의 Blender 씬</a></p>')
 if r.get('revision'):parts.append('<p><a href="'+esc(r['revision'])+'">수정 근거 JSON</a></p>')
 parts.append('<table><tr><th>공간</th><th>어색함 / 결함</th><th>레퍼런스 유사도</th><th>조치 / 재검수</th></tr>')
 for v in r['views']:
  parts.append('<tr>'+''.join('<td>'+esc(v[k])+'</td>' for k in ['space','awkwardness','similarity','action'])+'</tr>')
 parts.append('</table><div class="grid">')
 for v in r['views']:
  if not v.get('render'):continue
  parts.append('<div class="card"><h3>'+esc(v['space'])+'</h3>')
  for key,label in [('reference','레퍼런스'),('before','수정 전'),('render','실제 렌더')]:
   if v.get(key):parts.append('<p>'+label+'</p><a href="'+esc(v[key])+'"><img loading="lazy" src="'+esc(v[key])+'"></a>')
  parts.append('</div>')
 parts.append('</div><p>남은 문제: '+esc(r['remaining'])+'</p></article></details>')
parts.append('<p><a href="iteration_reviews.json">라운드별 원본 검수 기록</a></p></section><!-- ITERATION_REVIEWS_END -->')
section=''.join(parts);p=base/'progress.html';s=p.read_text()
if '<!-- ITERATION_REVIEWS_START -->' in s:s=re.sub(r'<!-- ITERATION_REVIEWS_START -->.*?<!-- ITERATION_REVIEWS_END -->',lambda _:section,s,flags=re.S)
else:s=s.replace('<section id="gpu-r5">',section+'<section id="gpu-r5">',1)
p.write_text(s)
