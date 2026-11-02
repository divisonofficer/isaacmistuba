"""Refresh current report entrypoints without changing source scenes, acceptance or history."""
from pathlib import Path
import json,datetime,shutil,subprocess,sys,html,hashlib
R=Path(__file__).resolve().parents[3];T=Path(__file__).parent;B=R/'data/venue_refs/floor_plans_v3';now=datetime.datetime.now(datetime.timezone.utc).isoformat();stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ');archive=B/'report_refresh_archive'/stamp;archive.mkdir(parents=True)
def read(p):return json.loads(p.read_text())
def save(p,a):p.write_text(json.dumps(a,ensure_ascii=False,indent=2))
def backup(p):
 if p.exists():q=archive/p.relative_to(B);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q)
slots_path=B/'scene_slots.json';slots=read(slots_path);approved=json.dumps(slots['slots'][0],sort_keys=True);backup(slots_path)
O=B/'commercial_office_floor_02';D=B/'dual_unit_residential_floor_03';snapshots={}
for d,latest,retained,full,count,full_folder,local_review in [(O,115,102,114,21,'full_suite_r114_cpu','wood115_review/blind_visual_review.json'),(D,130,97,116,43,'full_suite_r116_cpu','compact128_review/blind_visual_review.json')]:
 review_ready=(d/full_folder/'blind_visual_review.json').exists();review_round=full if review_ready else (112 if d==O else 108);review_count=count if review_ready else (21 if d==O else 41);review_folder=full_folder if review_ready else ('full_suite_r112_cpu' if d==O else 'full_suite_r108_gpu5')
 scene=d.name;source=R/f'out/infinigen_v2/kr_{scene}_4871250{2 if d==O else 3}/full'/f'scene_candidate_r{latest}_draft.blend';assert source.exists();status_path=d/'current_visual_status.json';backup(status_path);a=read(status_path);a.update(updated_at=now,raw_candidate_revision=retained,retained_candidate_revision=retained,pending_candidate_revision=latest,latest_submitted_candidate_revision=latest,last_complete_full_render_revision=full,last_complete_full_review_revision=review_round,last_complete_full_review_count=review_count,last_full_review=f'{review_folder}/blind_visual_review.json',last_full_review_independent_count=review_count,current_full_scene_review_complete=(latest==full and review_ready),photorealism_accepted=False,dataset_promoted=False,user_approved=False,required_view_count=21 if d==O else 43,current_goal_report='fine_current.html',revision_scope_note=f'Retained working source{retained}; latest unapproved draft{latest}. Latest completed full render{full}; last completed full independent review{review_round}. No acceptance.',latest_visually_reviewed_revision=115 if d==O else 128,latest_independent_review_revision=115 if d==O else 128,latest_local_review=local_review,latest_complete_full_suite_review_completed=review_ready,latest_complete_full_suite_accepted=False)
 a['latest_fine_progress']={'revision':115 if d==O else 128,'scope':('Office115 three matched pairs6originals+3refs independent MIXED:2A,1B; broad finish adoption held.114full21+6ref remainsFAIL' if d==O else 'Residential128six matched pairs12originals+2refs direct/independent complete:4B2ties,privacy/function localgain.Whole photorealism/nav unaccepted,black vertical strips remain. Full11643+5refs remainsFAIL,not128coverage.'),'critique':local_review,'full_scene_pass':False};a['last_complete_full_suite']={'revision':full,'path':full_folder+'/report.html','required_views':count,'independent_review_complete':review_ready,'whole_scene_verdict':'FAIL' if review_ready else 'pending','accepted':False};a['pending_full_suite']={'revision':latest,'path':'fine_current.html' if latest!=full else full_folder+'/report.html','required_views':21 if d==O else 43,'phase':'not_started_for_latest_draft' if latest!=full else ('complete_independent_review_failed' if review_ready else 'independent_review_pending'),'is_pending':latest!=full or not review_ready};save(status_path,a)
 state_path=d/'fine_current_state.json';backup(state_path);state=read(state_path);state['pending_candidate_revision']=latest;state['last_complete_full_render_revision']=full;state['last_complete_full_review_revision']=review_round
 if d==O:
  state['status']='r115 책상/테이블/수납장24개 사진 기반 1m 오크 마감·UV 시험 후보 저장.114기준 동일카메라3뷰 CPU6완료·직접/독립9원본검수2A1B혼합,115일괄채택보류.형상/배치/조명 변경없음,가구 구조 단순함·천장/외부전망·반복 미해결. r114 개별실 통창6개 설치, 후보6장 직접·독립검수:창 규모 개선·전체 주요결함 잔존. 동일카메라6쌍12장 직접·독립검수 B선호6/6. 최신114 전체21뷰·참조6장 독립 전체검수 완료:REF/REAL 미달. r113 화단 전후8장 직접·독립검수 국소개선. r112 전체21뷰·참조6장 독립검수는 전체 REF/REAL FAIL. 개별실 창·리셉션·외부환경·재질·천장 미해결. 승격 없음.';state['full_suite_render_in_progress_revision']=None;state['checks'].append({'path':'planters113_review/report.html','result':'화단6개·공유접란18개 전후4쌍:국소개선, 반복잎·평평한흙 미해결'})
 else:
  job=read(d/'full_suite_r116_cpu/job.json');receipt=read(d/'full_suite_r116_cpu/candidate/render_receipt.json') if (d/'full_suite_r116_cpu/candidate/render_receipt.json').exists() else {};done=len(receipt.get('frames',[]));render_stage=('전체 독립검수 REF/REAL FAIL' if review_ready else '렌더 완료·독립전체검수 중') if done==43 else '렌더 진행';state['status']='r129 실제 중복벽 접합 정리 후보 저장·동일카메라2쌍 직접검수에서 검은 띠 제거 확인.4제안 경로 제한검사 유지.독립129검수/전체층 검수 대기. r128 TV native 변환 복원:127 수평 TV/통로 충돌 실패를 보존.128 실제 크기·바닥/벽 접촉 및 양쪽 제안600mm private 경로 제한 검사 통과.126/128 동일카메라6쌍 완료·14원본 직접/독립검수4B2동률. TV방향/변기시선 국소개선,검은수직띠/빈벽/균일직물·전체실사성 미해결. r126 native 문틀15곳 하단 설치/실제 매입등2개 교체.6쌍 원본12장+참조1 직접·독립검수 국소 B6/6.18정적 문틀 표면 스크린 충돌없음1→13;다른 방 동선/가구·화분은 미해결.125는 출입 B2/거실동률2/역방향A2 혼합 판정으로 TV방향·WC시선 재배치 필요. r116 전체43뷰+참조5장 독립 REF/REAL FAIL;최신128 전체뷰/독립전체검수는 아직 없음.119의 걸레받이 누락 부분검사 PASS는 철회된 기록으로 보존.실사성 승인·승격 없음.';state['full_suite_render_in_progress_revision']=116 if done<43 else None;state['checks'].append({'path':'full_suite_r116_cpu/report.html','result':f'통합116 전체43뷰 {render_stage} {done}/43;시각·동선 합격 전'});state['checks'].append({'path':'stair115_review/report.html','result':'계단 전후4장 직접·독립검수:국소 구조개선, 사진수준/전체동선 합격 아님'});snapshots['residential_frames']=done
 if d==D:
  state['checks'].append({'path':'compact128_review/report.html','result':'128 TV자세/크기 복원·접촉/두600mm 경로 제한통과.6쌍 완료·14원본 직접/독립4B2동률.국소개선·전체미달.127은 TV수평/통로침범 실패 보존'})
  state['updates']=[x for x in state['updates'] if not x.startswith(('r127 후보 저장:','r128 후보 저장:'))]+['r128 후보 저장:127 수평TV 실패 보존·native 스튜디오 변환 복원.양쪽 제안600mm 경로/실제 크기·접촉 제한검사 통과.126/128 CPU6쌍 완료·직접/독립14장4B2동률,국소개선/전체미달.']
 if d==D:state['checks'].append({'path':'navigation128_preflight/report.html','result':'128 전체2058메쉬 지상층 스크린:101안방/발코니/드레스룸 연결 회복,여러침실/욕실·102현관 분리 잔존.정적 제안private/core4경로 제한통과,전체동선 미달'})
 if d==O:
  state['checks'].append({'path':'wood115_review/report.html','result':'115 선택24가구 목재 마감/metric UV만 변경.114대비3뷰 CPU6 완료·직접/독립9장2A1B혼합,일괄채택보류'})
  state['updates']=[x for x in state['updates'] if not x.startswith('r115 마감 시험:')]+['r115 마감 시험:선택24가구 사진 기반오크 albedo/roughness/tangent normal·실제면별 metre UV.형상/조명/기존105캐비닛/바닥/문 유지.3뷰 직접/독립9장 검수2A1B,일괄채택보류.']
 state['checks']=list({(x['path'],x['result']):x for x in state['checks']}.values());state['updated_at']=now;save(state_path,state)
 for row in slots['slots']:
  if row['scene_id']!=scene:continue
  row.update(updated_at=now,status='photorealism_rework_in_progress',revision=f'r{retained}',report=str(d/'fine_current.html'),inspection=str(d/'fine_current.html')+'#compare',pending_candidate_revision=latest,pending_candidate_blend=str(source),overview=str(d/full_folder/'candidate/overview.png'),overview_revision=f'r{full}',render_count=count,visual_acceptance=False,dataset_promoted=False,user_approved=False)
# Keep user-requested finalization entry source-bound.
row=next(x for x in slots['slots'] if x['slot']==3);row.update(status='final_review_in_progress',report=str(D/'finalization/report.html'),inspection=str(D/'finalization/report.html')+'#common')
a=read(D/'current_visual_status.json');a.update(current_goal_report='finalization/report.html',latest_visually_reviewed_revision=129,finalization_phase='latest_source_full_review_in_progress');a['pending_full_suite'].update(revision=130,path='finalization/report.html',phase='rendering_latest_source',is_pending=True);save(D/'current_visual_status.json',a)
# Correct slot4's reference-only label using its actual completed shell render.
shell=B/'rural_stone_cottage_04/shell_r0_gpu5/candidate/overview_shell_r0.png'
if shell.exists():
 for row in slots['slots']:
  if row['slot']==4 and not row.get('worker_task') and not row.get('pending_candidate_blend'):row.update(status='architecture_shell_only',revision='r0 shell',overview_kind='render',overview=str(shell),overview_revision='r0 shell',render_count=1,blend=str(R/'out/infinigen_v2/kr_rural_stone_cottage_04_48712504/full/scene.blend'),visual_acceptance=False,dataset_promoted=False,user_approved=False,updated_at=now)
assert json.dumps(slots['slots'][0],sort_keys=True)==approved;slots['updated_at']=now;save(slots_path,slots)
# Refresh current wrappers; archive originals once so source-specific history remains accessible.
for d,full in [(O,'full_suite_r114_cpu'),(D,'full_suite_r116_cpu')]:
 for name in ['progress.html','inspection_candidate.html']:
  old=d/name;history=d/(old.stem+'_archive_before_current_refresh.html')
  if old.exists() and not history.exists():shutil.copyfile(old,history)
  newer='<a href="full_suite_r116_cpu/report.html">주거116 전체43뷰 완료·검수 미달</a> · ' if d==D else '<a href="full_suite_r114_cpu/report.html">사무실114 전체21뷰 완료·검수 미달</a> · <a href="glazing114_review/report.html">통창114 비교</a> · '
  old.write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>최신 씬 보고서</title><style>body{font:18px/1.8 system-ui;max-width:1000px;margin:auto;padding:30px}a{display:inline-block;margin:8px}</style><h1>최신 씬 보고서</h1><p>갱신 '+html.escape(now)+'</p><p>전체 실사성 최종 미달·데이터셋 승격 없음. 국소 검수 완료와 전체 승인을 구분합니다.</p><p><a href="fine_current.html">현재 탭형 종합 보고서</a> · '+newer+'<a href="'+full+'/report.html">마지막 완료 전체 렌더</a> · <a href="../all_room_renders_latest/report.html">두 씬 전체 방</a></p><p><a href="'+history.name+'">이전 고정 기록</a></p></html>')
old=B/'all_room_renders/report.html'
if old.exists():
 hist=old.with_name('report_archive_before_current_refresh.html')
 if not hist.exists():shutil.copyfile(old,hist)
 old.write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=../all_room_renders_latest/report.html"><title>최신 전체 방 보고서</title><a href="../all_room_renders_latest/report.html">최신 전체 방 보고서 열기</a> · <a href="report_archive_before_current_refresh.html">이전 고정 기록</a></html>')
# Main hub must describe shell separately and use latest completed gallery URL.
p=T/'index_report.py';s=p.read_text().replace('href="all_room_renders/report.html"','href="all_room_renders_latest/report.html"')
if "caption='건축 셸만 생성" not in s:s=s.replace(" if idx and retained is not None:"," if row.get('status')=='architecture_shell_only':caption='건축 셸만 생성 · 가구·재질·실사 검수 전'\n if idx and retained is not None:")
if "image_scope='건축 셸" not in s:s=s.replace("  figure=f'<figure>","  if row.get('status')=='architecture_shell_only':image_scope='건축 셸 시험 렌더r0 · 실사성 미달'\n  figure=f'<figure>")
p.write_text(s)
for script in ['report_current_full_defects.py','report_core_traps121_matched.py','report_all_traps122.py','report_living125_matched.py','report_installation126_matched.py','report_native_media_products.py','report_wood115_matched.py','report_compact128_matched.py','report_wall129_matched.py','report_residential_finalization.py','report_navigation128_preflight.py','report_navigation126_preflight.py','report_navigation122_preflight.py','report_navigation125_preflight.py','report_curtain_optical_trials.py','report_curtain120_products.py','report_core120_access.py','report_core119_access.py','report_office114_progress.py','report_glazing114_matched.py','report_planters113_matched.py','report_bedroom111_matched.py','report_stair115_matched.py','report_residential116_progress.py','report_latest_all_rooms.py','fine_current_report.py']:
 subprocess.run([sys.executable,str(T/script)],check=True,cwd=R)
# Restore complete review state in derived local evidence (not an acceptance flag).
for pth in [O/'planters113_review/evidence.json',D/'bedroom111_review/evidence.json',D/'stair115_review/evidence.json']:
 if pth.exists():a=read(pth);a.update(visual_review='completed_local_improvement_only',accepted=False);save(pth,a)
# Full-suite report metadata accurately distinguishes completed FAIL from pending.
for d,folder in [(O,'full_suite_r112_cpu'),(D,'full_suite_r108_gpu5')]:
 p=d/folder;ev=p/'gallery_evidence.json';a=read(ev);a.update(visual_review_complete=True,accepted=False,independent_review='blind_visual_review.json',whole_scene_verdict='FAIL');save(ev,a);page=(p/'report.html').read_text().replace('full visual/independent review pending','full independent review complete: FAIL').replace('full visual review pending','full independent review complete: FAIL')
 if 'href="blind_visual_review.json"' not in page:page=page.replace('<div class="grid">','<p><a href="blind_visual_review.json">독립 전체 검수: FAIL</a></p><div class="grid">')
 (p/'report.html').write_text(page)
# Plain factual handoff, current source and completed suites are separate.
lines=['# Scene progress — '+now,'','## commercial_office_floor_02','',
'- Latest saved unapproved draft r115; retained working source r102; no promotion.',
'-115 changes selected wood finish/metric UV on24 existing desk/table/storage objects; raw geometry/poses unchanged. Existing105 cabinet/floors/doors retained.',
'- Independent full114 review:21 candidates+6 references, REF/REAL FAIL.',
'- Full-suite source/frame hashes and27-original review coverage verified.',
'- Current114 native full-height glazing local6 pairs prefer B; whole-floor quality remains below target.',
'- Open: coherent leafy exterior, integrated ceiling lights/services, desk/support construction, repeated wood/carpet and usage.',
'- Eterna IP65 office-light asset remains held: industrial weatherproof design differs from reference.',
'- Existing real fixture/HVAC library pointers requested from SUB via Orca; no acknowledgement/adoption claimed.',
'-115 matched3pairs6renders+3refs independently reviewed:2A,1B. Broad finish adoption held; cabinet stripe improved but desktops/reference warmth regress.',
'- Report: commercial_office_floor_02/fine_current.html.','',
'## dual_unit_residential_floor_03','',
'- Latest saved unapproved draft r128; retained working source r97; no promotion.',
'- Since126: compact native console/TV faces seating, authored privacy returns and ficus relocation; 101 photographic oak/102 dark finish.',
'-127 failed actual route check: flat TVs intruded into both paths; preserved.128 recovers evaluated native studio poses without rescaling.',
'-128 reopened native meshes/dimensions/console floor and TV wall interface checked; two proposed600mm private-hall paths clear in bounded static test.',
'-126/128 matched6pairs12renders+2refs direct/independent complete:4B2ties,TV facing/privacy local gains; black strips and room/material/reference gaps remain.',
'- Since125:15 native fixed frame bases embedded80mm; exact leaf/handle/other vertices/topology/material slots unchanged.',
'- Two laundry floor-level boxes replaced by real native6294-face recessed lights; ceiling fit and preserved transport power checked.',
'- Legacy WC substring selector corrected: actual source125 broad96 matches vs10 actual WC body suffix matches.',
'- Static18-door prism screen: clear1/18 to13/18;8 anomalous/upper frame cases excluded and remain open.',
'- Ground-floor126 all2049-render-mesh screen expands connected102 rooms and101foyer/laundry; several rooms still disconnected.',
'- Private-hall exact floor footprint uncovered0m² both units; proposed approach intersects small plant sets, not a floor gap.',
'- Matched126 six pairs12 originals plus bathroom reference independently reviewed: local B6/6, whole-room realism stillFAIL.',
'- Full125 local14-original review: entry B2, living ties2, reverse A2; TV alignment/open-WC sightlines remain high severity.',
'- Full11643 CPU views+5 refs independently reviewed FAIL; it does not cover later126 edits. No latest126 full suite yet.',
'- Five real media donors10 views+1 ref independently reviewed: Morrison/55TV now installed only in unreviewed128 candidate.',
'- Next: remove diagnosed coincident architectural wall surfaces causing black bands, repair native bedroom2 door/aperture fit,then matched and latest-source full suite checks.',
'- Open original scope: clothes/bedding/cushions, bathroom material/joinery realism, exterior and global navigation.',
'- Report: dual_unit_residential_floor_03/installation126_review/report.html.','',
'GPU: no fresh explicit allocation verified; CPU only. Orca sends are queued, not proof of recipient/UI update.',
'Hub: /jarvis/project/robomituba/data/venue_refs/floor_plans_v3/scene_slots.html',
'All-room completed gallery: /jarvis/project/robomituba/data/venue_refs/floor_plans_v3/all_room_renders_latest/report.html','']
Path('/bean/ir_dataset_work/codex_review/PROGRESS_scene_agent.md').write_text('\n'.join(lines))
manifest={'updated_at':now,'approved_PH_slot_unchanged':True,'current_report_archive':str(archive),'office_latest_draft':115,'office_last_full_render':114,'office_last_full_review':114 if (O/'full_suite_r114_cpu/full_review_coverage_verified.json').exists() else 112,'residential_latest_draft':130,'residential_last_full_render':116,'residential_last_full_review':116 if (D/'full_suite_r116_cpu/blind_visual_review.json').exists() else 108,'full_scene_accepted':False,'dataset_promoted':False,'hub':str(B/'scene_slots.html'),'snapshots':snapshots};save(B/'report_refresh_receipt.json',manifest);print('ALL_CURRENT_REPORTS_REFRESHED',now)
