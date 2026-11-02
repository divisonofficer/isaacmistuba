"""Compact evidence-led realism reassessment and paired-render round report."""
import json,html,datetime
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[3];B=ROOT/'data/venue_refs/floor_plans_v3';esc=lambda x:html.escape(str(x))
for scene,revision in [('commercial_office_floor_02',20),('dual_unit_residential_floor_03',24)]:
 ref=B/scene;data=json.loads((ref/'realism_evaluation.json').read_text());revision=data.get('current_comparison_revision',data.get('current_candidate_revision',revision));out=ref/f'realism_r{revision}';job=ref/f'realism_pair_job_r{revision}.json';state=json.loads(job.read_text()) if job.exists() else {};preview=ref/'realism_previews';preview.mkdir(exist_ok=True)
 def image(path,caption):
  path=Path(path)
  if not path.exists():return '<p>렌더 대기: '+esc(caption)+'</p>'
  name=path.relative_to(ref).as_posix().replace('/','_').replace('.png','.jpg');target=preview/name
  with Image.open(path) as im:im=im.convert('RGB');im.thumbnail((800,600));im.save(target,quality=86,optimize=True)
  return '<figure><a href="'+str(path.relative_to(ref))+'"><img loading="lazy" src="'+str(target.relative_to(ref))+'" alt="'+esc(caption)+'"></a><figcaption>'+esc(caption)+'</figcaption></figure>'
 inventory=data.get('whole_scene_inventory',{});inventory_html='<h2>전체 재질·메시 조사</h2><p>렌더 메시 '+str(inventory.get('renderable_meshes','조사 중'))+'개 · 실제 사용 재질 '+str(inventory.get('assigned_materials_including_curves','조사 중'))+'개 · 기존 태그 미분류 '+str(inventory.get('unclassified_materials','조사 중'))+'개</p><p>'+esc(data.get('coverage_note',''))+'</p><a href="realism_whole_scene_inventory.json">전수 목록과 실제 채널/형상 수치</a>'
 if data.get('blind_review_report'):inventory_html+='<p><a href="'+esc(data['blind_review_report'])+'">히스토리 없는 독립 서브에이전트 3건 검수 결과</a></p>'
 if data.get('breakout_diagnostic_report'):inventory_html+='<p><a href="'+esc(data['breakout_diagnostic_report'])+'">탕비실 A/B/C 및 형상 분리 실험</a></p>'
 if data.get('current_goal_report'):inventory_html+='<p><a href="'+esc(data['current_goal_report'])+'">현재 실사성 goal · 최신 보정과 근접 비교</a></p>'
 criteria=''.join('<li><b>'+esc(c['criterion'])+'</b><br>'+esc(c['acceptance'])+'</li>' for c in data['criteria']);issues=''
 for issue in data['issues']:
  issues+='<article><h3>'+esc(issue['severity'])+' · '+esc(issue['id'])+'</h3><p>'+esc(issue['finding'])+'</p><p>수정: '+esc(issue['next'])+'</p>'
  if issue.get('evidence'):issues+=image(ref/issue['evidence'],'기준본 · '+issue['id'])
  issues+='</article>'
 compare='';views=json.loads((out/'views.json').read_text()) if (out/'views.json').exists() else []
 for i,view in enumerate(views):
  name=view['name'];compare+='<details'+(' open' if i==0 else '')+'><summary>'+esc(name)+'</summary><div class="pair">'+image(out/'baseline'/(name+'.png'),'이전 기준본')+image(out/'candidate'/(name+'.png'),'새 후보 r'+str(revision))+'</div></details>'
 records=[]
 for r in sorted(ref.glob('realism_refinement_r*.json'),key=lambda p:int(p.stem.rsplit('r',1)[1])):
  d=json.loads(r.read_text());records.append('<details><summary>'+esc(r.stem)+'</summary><pre>'+esc(json.dumps({k:v for k,v in d.items() if k!='created_objects'},ensure_ascii=False,indent=2))+'</pre></details>')
 review=ref/f'realism_visual_review_r{revision}.json'
 if review.exists():records.insert(0,'<pre>'+esc(review.read_text())+'</pre>')
 page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>재질·메시 실사성 Fine 검수</title><style>body{font:16px/1.6 system-ui;background:#f2f4f7;color:#243047;margin:0}main{max-width:1150px;margin:auto;padding:24px}section,article{background:white;padding:20px;border-radius:10px;margin:16px 0}section[hidden]{display:none}nav{display:flex;gap:10px}button{padding:10px 18px;cursor:pointer}img{max-width:100%;height:auto}.pair{display:flex;flex-wrap:wrap;gap:12px}.pair figure{flex:1;min-width:260px;margin:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}.notice{background:#fff0cb;padding:14px}summary{cursor:pointer;padding:12px}</style><main><a href="../scene_slots.html">세 슬롯 전체 현황</a> · <a href="progress.html">기존 라운드 보고서</a>'''
 page+='<h1>'+('사무실' if scene=='commercial_office_floor_02' else '2세대 주거층')+' · 재질·메시 실사성</h1><p class="notice">실사성 최종 합격 전. 공간·동선 검사 통과와 실사성 판정을 구분합니다. 기준본 r'+str(data['baseline_revision'])+' → 보정 후보 r'+str(revision)+'.</p><p>갱신 '+datetime.datetime.now(datetime.timezone.utc).isoformat()+' · 비교 렌더 '+esc(state.get('phase','대기'))+'</p>'
 full_revision=data.get('current_candidate_revision',revision);full_job=ref/f'final_render_job_r{full_revision}.json'
 if full_job.exists():
  fj=json.loads(full_job.read_text());page+='<p class="notice">전체 후보 r'+str(full_revision)+' · '+esc(fj.get('phase'))+' · CPU · 최종 전체 시각 검수 전</p>'
 followup=data.get('followup_review')
 if followup:page+='<article><h2>독립 검수 후 보정 r'+str(followup['revision'])+'</h2><p>'+esc(followup['decision'])+'</p><ul>'+''.join('<li>'+esc(x)+'</li>' for x in followup['findings'])+'</ul><p>전체 실사성 최종 합격 전. 이 결과는 명시한 근접 시점의 비교입니다.</p></article>'
 latest=data.get('latest_strict_review')
 if latest:
  page+='<article><h2>최신 실사성 판정: 보완 필요</h2><p>'+esc(latest['reason'])+'</p><ul>'+''.join('<li>'+esc(x)+'</li>' for x in latest['remaining_visual_findings'])+'</ul><p>전체 검수 '+str(latest['full_source_views_reviewed'])+'시점 · r'+str(latest['full_source_revision'])+'</p></article>'
  light=ref/('realism_r'+str(latest['revision']))
  compare+='<h2>채택하지 않은 천장 조명 감소 실험</h2><p>'+esc(latest['reason'])+'</p>'
  for path in sorted((light/'candidate').glob('*.png')):
   compare+='<details><summary>'+esc(path.stem)+'</summary><div class="pair">'+image(light/'baseline'/path.name,'기준 조명')+image(path,'천장 조명 감소 · 미채택')+'</div></details>'
 page+='<nav>'+''.join('<button data-tab="'+k+'">'+v+'</button>' for k,v in [('evaluation','평가'),('compare','동일 시점 A/B'),('rounds','라운드 기록')])+'</nav><section id="evaluation">'+inventory_html+'<h2>평가 기준</h2><ul>'+criteria+'</ul><h2>주요 미해결 결함</h2>'+issues+'</section><section id="compare" hidden>'+compare+'</section><section id="rounds" hidden>'+''.join(records)+'</section></main><script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab;location.hash=b.dataset.tab};const start=Array.from(document.querySelectorAll("[data-tab]")).find(b=>b.dataset.tab===location.hash.slice(1));if(start)start.click();</script></html>'
 (ref/'realism_progress.html').write_text(page);print(ref/'realism_progress.html')
