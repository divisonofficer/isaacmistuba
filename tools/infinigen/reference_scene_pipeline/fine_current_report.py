"""Small state-driven Fine report; source snapshots and diagnostic images remain explicitly scoped."""
import datetime,html,json
import subprocess,sys
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[3];B=ROOT/'data/venue_refs/floor_plans_v3';esc=lambda x:html.escape(str(x))
for scene in ['commercial_office_floor_02','dual_unit_residential_floor_03']:
 ref=B/scene;state=json.loads((ref/'fine_current_state.json').read_text());preview=ref/'fine_current_previews';preview.mkdir(exist_ok=True)
 def picture(item):
  path=ref/item['path'];label=item['label']
  if not path.exists():return '<figure><p>'+esc(label)+' · 렌더 대기</p></figure>'
  name=item['path'].replace('/','_').replace('.png','.jpg');target=preview/name
  if not target.exists() or target.stat().st_mtime<path.stat().st_mtime:
   with Image.open(path) as im:im=im.convert('RGB');im.thumbnail((800,600));im.save(target,quality=87,optimize=True)
  return '<figure><a href="'+esc(item['path'])+'"><img loading="lazy" src="'+esc(str(target.relative_to(ref)))+'" alt="'+esc(label)+'"></a><figcaption>'+esc(label)+'</figcaption></figure>'
 def sections(items):
  return ''.join('<details'+(' open' if i==0 else '')+'><summary>'+esc(section['title'])+'</summary><p>'+esc(section.get('note',''))+'</p><div class="pair">'+''.join(picture(p) for p in section['images'])+'</div></details>' for i,section in enumerate(items))
 def bounded_sections(items,kind):
  latest=items[:6];older=items[6:];links=[]
  for start in range(0,len(older),6):
   number=start//6+1;name=f'fine_{kind}_archive_{number:02}.html';links.append('<a href="'+name+'">'+str(number)+'</a>')
   body=sections(older[start:start+6])
   archive='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>이전 검수 기록 '+str(number)+'</title><style>body{font:16px/1.7 system-ui;max-width:1150px;margin:auto;padding:20px}.pair{display:flex;flex-wrap:wrap;gap:12px}figure{flex:1;min-width:260px;margin:0}img{max-width:100%;height:auto}summary{cursor:pointer;padding:14px}</style><a href="fine_current.html#'+kind+'">현재 보고서로</a><h1>이전 검수 기록 '+str(number)+'</h1>'+body+'</html>'
   (ref/name).write_text(archive)
  return sections(latest)+('<p>이전 기록 페이지 · '+' · '.join(links)+'</p>' if links else '')
 def archive_list(items,kind,render_items):
  links=[]
  for start in range(0,len(items),30):
   number=start//30+1;name=f'fine_{kind}_archive_{number:02}.html'
   page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>이전 기록</title><style>body{font:16px/1.7 system-ui;max-width:1000px;margin:auto;padding:20px}li{margin:12px 0}</style><a href="fine_current.html#current">현재 보고서</a><h1>이전 기록 '+str(number)+'</h1>'+render_items(items[start:start+30])+'</html>'
   assert len(page.encode())<100000
   (ref/name).write_text(page);links.append('<a href="'+name+'">'+str(number)+'</a>')
  return '<p>이전 '+('변경' if kind=='updates' else '검사')+' 기록 '+str(len(items))+'건 · '+' · '.join(links)+'</p>'
 recent=state['updates'][-6:];older=state['updates'][:-6]
 current='<p>'+esc(state['status'])+'</p><ul>'+''.join('<li>'+esc(x)+'</li>' for x in recent)+'</ul>'
 if older:current+=archive_list(older,'updates',lambda items:'<ul>'+''.join('<li>'+esc(x)+'</li>' for x in items)+'</ul>')
 checks=state.get('checks',[])
 def check_list(items):return '<ul>'+''.join('<li>'+esc(x['result'])+' · <a href="'+esc(x['path'])+'">근거</a></li>' for x in items)+'</ul>'
 current+='<h2>최근 검사 근거와 범위</h2>'+check_list(checks[-6:])
 if len(checks)>6:current+=archive_list(checks[:-6],'checks',check_list)
 remaining='<ul>'+''.join('<li>'+esc(x)+'</li>' for x in state['remaining'])+'</ul><p>사용자 승인 전 데이터셋 승격 없음. PH r39 승인본 유지. '+esc(state.get('render_resource_note','현재 CPU 렌더.'))+'</p>'
 tabs={'current':('현재',current),'compare':('비교 렌더',bounded_sections(state['comparisons'],'compare')),'diagnostics':('원인 분리',bounded_sections(state.get('diagnostics',[]),'diagnostics')),'remaining':('남은 과제',remaining)}
 page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+esc(state['title'])+'</title><style>body{font:16px/1.7 system-ui;max-width:1150px;margin:20px auto;padding:20px}nav{display:flex;gap:12px;flex-wrap:wrap}button{padding:10px;cursor:pointer}section{background:#f2f4f7;padding:20px;margin-top:18px}section[hidden]{display:none}.pair{display:flex;flex-wrap:wrap;gap:12px}.pair figure{flex:1;min-width:260px;margin:0}img{max-width:100%;height:auto}li{margin:12px 0}summary{cursor:pointer;padding:14px}figcaption{font-size:14px}</style><a href="../scene_slots.html">씬 현황</a> · <a href="realism_progress.html">이전 검수 기록</a><h1>'+esc(state['title'])+'</h1><p>실사성 goal 활성 · 전체 최종 합격 전 · 갱신 '+datetime.datetime.now(datetime.timezone.utc).isoformat()+'</p><nav>'+''.join('<button data-tab="'+k+'">'+v[0]+'</button>' for k,v in tabs.items())+'</nav>'+''.join('<section id="'+k+'"'+(' hidden' if k!='current' else '')+'>'+v[1]+'</section>' for k,v in tabs.items())+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab;location.hash=b.dataset.tab};const initial=Array.from(document.querySelectorAll("[data-tab]")).find(b=>b.dataset.tab===location.hash.slice(1));if(initial)initial.click();</script></html>'
 (ref/'fine_current.html').write_text(page);assert len(page.encode())<100000
 p=ref/'realism_evaluation.json';data=json.loads(p.read_text());data['current_goal_report']='fine_current.html';data['retained_working_candidate_revision']=state['raw_candidate_revision'];data['current_refinement_candidate_revision']=state.get('pending_candidate_revision',state['raw_candidate_revision']);p.write_text(json.dumps(data,ensure_ascii=False,indent=2));print(scene,len(page.encode()))
subprocess.run([sys.executable,str(Path(__file__).with_name('index_report.py'))],check=True)
