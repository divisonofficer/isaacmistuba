"""Small variable-slot report hub; references and actual renders are distinguished."""
import datetime,html,json
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'data/venue_refs/floor_plans_v3';slots=json.loads((base/'scene_slots.json').read_text())['slots'];esc=lambda x:html.escape(str(x));previews=base/'slot_previews';previews.mkdir(exist_ok=True);labels=[row.get('title',{'pivot_courtyard_house_01':'중정 주택','commercial_office_floor_02':'사무실','dual_unit_residential_floor_03':'2세대 주거층'}.get(row['scene_id'],row['scene_id'])) for row in slots];cards=[];buttons=[]
for idx,row in enumerate(slots):
 scene=row['scene_id'];ref=base/scene;current_path=ref/'current_visual_status.json';current=json.loads(current_path.read_text()) if current_path.exists() else {};ready=row.get('status')=='accepted' or bool(current.get('photorealism_accepted') and current.get('current_full_scene_review_complete'));revision=row.get('revision','');retained=current.get('retained_candidate_revision');pending=current.get('pending_candidate_revision');reference_only=row.get('overview_kind')=='reference';caption='사용자 승인본 · 보존' if idx==0 else ('레퍼런스 등록 · 3D 씬·렌더 생성 전' if reference_only else ('전체 실사성 검수 완료 · 사용자 검토 대기' if ready else '실사성 개선 중 · 전체 최종 합격 전'))
 if row.get('worker_task'):
  caption={'reference_authoring_in_progress':'평면/다층 구조 작성 중 · 실제 렌더 대기','native_architecture_generated':'건축 씬 저장 · 실제 가구/렌더 작업 중','furnished_candidate_rendering':'실제 가구 후보 CPU 렌더 중 · 검수 전','furnished_candidate_rendered_review_pending':'실제 가구 후보 렌더 · 검수/완성 전'}.get(row.get('status'),'씬 제작 중 · 전체 검수 전')
 if row.get('status')=='architecture_shell_only':caption='건축 셸만 생성 · 가구·재질·실사 검수 전'
 if idx and retained is not None:caption+=f' · 작업 기준 r{retained}'
 if idx and pending is not None:caption+=f' · 시험 r{pending} 저장·검수 대기' if scene=='dual_unit_residential_floor_03' and pending==128 else f' · 시험 r{pending} 검수 중'
 receipts=sorted((ref/'renders').glob('r*/render_receipt.json'),key=lambda p:int(p.parent.name[1:])) if idx else []
 image=Path(row.get('overview',''));render_rev=row.get('overview_revision',revision)
 if receipts and not row.get('overview_revision'):
  receipt=json.loads(receipts[-1].read_text());frame=next((f for f in receipt['frames'] if f['name']=='overview'),None)
  if frame:image=Path(frame['path']);render_rev=receipts[-1].parent.name
 preview=previews/(scene+'.jpg')
 if image.is_file():
  with Image.open(image) as im:im=im.convert('RGB');im.thumbnail((1100,825));im.save(preview,quality=85,optimize=True)
  image_scope='사용자 제공 레퍼런스 · 생성한 3D 렌더가 아님' if reference_only else (f'마지막 전체 검수 평면 {render_rev} · 현재 작업 기준/시험 후보와 구분' if idx else f'승인본 실제 평면 {render_rev}')
  if row.get('worker_task'):image_scope=f'최근 실제 시험 평면 {render_rev} · 최신 저장 후보/완성 검수와 구분'
  if row.get('status')=='architecture_shell_only':image_scope='건축 셸 시험 렌더r0 · 실사성 미달'
  figure=f'<figure><img src="{esc(preview.relative_to(base))}" alt="{esc(labels[idx])} 실제 평면"><figcaption>{esc(image_scope)} · 가벼운 미리보기</figcaption></figure>'
 else:figure='<p>전체 평면 렌더 준비 중</p>'
 compact=ref/'fine_current.html';report=(Path(row['report']) if row.get('status','').startswith('final_review') else compact if idx and compact.exists() else Path(row['report'])).relative_to(base);inspection=str(report)+'#common' if row.get('status','').startswith('final_review') else str(report)+'#compare' if idx and compact.exists() else str(Path(row.get('inspection',str(ref/'inspection_candidate.html'))).relative_to(base))
 cards.append(f'<section id="slot{idx+1}" {"hidden" if idx!=1 else ""}><h2>슬롯 {idx+1} · {esc(labels[idx])}</h2><p class="state">{esc(caption)}</p><p><a href="{esc(report)}">탭형 상세 보고서</a> · <a href="{esc(inspection)}">검수탭 열기</a></p>{figure}<p>원본 평면도, 공간별 레퍼런스, 재질 A/B, 물리 검사와 라운드별 지적은 상세 보고서에 있습니다.</p><details><summary>파일 절대경로</summary><pre>작업 기준: {esc(row.get("blend",""))}\n검수 후보: {esc(row.get("pending_candidate_blend",""))}\n보고서: {esc(row["report"])}</pre></details></section>')
 buttons.append(f'<button role="tab" aria-selected="{str(idx==1).lower()}" data-slot="slot{idx+1}">{idx+1}. {esc(labels[idx])}</button>')
page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>평면도 기반 Infinigen 씬 · 슬롯 보고서</title><style>body{font:16px/1.6 system-ui;background:#f3f5f8;color:#243047;margin:0}main{max-width:1150px;margin:auto;padding:24px}nav{display:flex;flex-wrap:wrap;gap:10px}button{padding:12px 20px;cursor:pointer;border:1px solid #aab7c5;border-radius:8px;background:white}button[aria-selected=true]{background:#23475c;color:white}section{margin-top:20px;background:white;padding:24px;border-radius:12px}section[hidden]{display:none}img{max-width:100%;height:auto}figure{margin:16px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}.state{font-weight:600}a{color:#17618d}</style><main><h1>평면도 기반 Infinigen 씬</h1><p>승인된 주택 r39는 보존합니다. 새 씬들은 사용자 검토 후 별도로 데이터셋 승격합니다. 모든 방 갤러리: <a href="all_room_renders_latest/report.html">사무실·주거층 렌더</a> · <a href="review_backlog_current.html">전체 독립검수·미해결 우선과제</a></p><nav role="tablist">'''+''.join(buttons)+'</nav>'+''.join(cards)+'''</main><script>function show(id){for(const s of document.querySelectorAll('section'))s.hidden=s.id!==id;for(const b of document.querySelectorAll('[data-slot]'))b.setAttribute('aria-selected',String(b.dataset.slot===id));location.hash=id}for(const b of document.querySelectorAll('[data-slot]'))b.onclick=()=>show(b.dataset.slot);if(document.getElementById(location.hash.slice(1)))show(location.hash.slice(1));</script></html>''';(base/'scene_slots.html').write_text(page);print(base/'scene_slots.html')
