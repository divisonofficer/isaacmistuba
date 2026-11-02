"""Refresh current views without resetting authoritative source/review state to old rounds.

Scene producers own candidates/metadata. This entrypoint archives generated documents,
refreshes evidence-bound views, and proves it did not alter those authoritative states.
It does not launch Blender, allocate GPUs, promote scenes, or rebuild historical reviews.
"""
from pathlib import Path
import datetime,hashlib,json,shutil,subprocess,sys
R=Path(__file__).resolve().parents[3];T=Path(__file__).parent;B=R/'data/venue_refs/floor_plans_v3';stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ');archive=B/'report_refresh_archive'/('safe_views_'+stamp);archive.mkdir(parents=True)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=Path('/bean/ir_dataset_work/codex_review/agent_scenes.json');registry=json.loads(manifest.read_text());assert len({r['id'] for r in registry})==len(registry)
for row in registry:assert Path(row['current_candidate_blend']).is_file(),row['id']
authoritative=[B/'scene_slots.json',manifest]
for row in registry:
 folder=Path(row['folder']);folder=folder if folder.is_absolute() else R/folder
 p=folder/'current_visual_status.json'
 if p.exists():authoritative.append(p)
before={str(p):sha(p) for p in authoritative};approved=json.loads((B/'scene_slots.json').read_text())['slots'][0];blend_stats={row['current_candidate_blend']:(Path(row['current_candidate_blend']).stat().st_size,Path(row['current_candidate_blend']).stat().st_mtime_ns) for row in registry}
outputs=[B/'scene_slots.html',B/'all_room_renders_latest/report.html',B/'all_room_renders_latest/evidence.json',B/'review_backlog_current.html',B/'review_backlog_current.json']
for folder in ['commercial_office_floor_02/wood115_review','dual_unit_residential_floor_03/finalization','dual_unit_residential_floor_03/bathroom_door132_review','dual_unit_residential_floor_03/entry133_review','dual_unit_residential_floor_03/portal132_review']:
 outputs +=[B/folder/'report.html',B/folder/'evidence.json',B/folder/'status.json']
for p in outputs:
 if p.exists():q=archive/p.relative_to(B);q.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,q)
runs=[]
for script,required in [('report_current_full_defects.py',B/'dual_unit_residential_floor_03/finalization/full130_independent_coverage_verified.json'),('report_latest_all_rooms.py',B/'dual_unit_residential_floor_03/final_audit_r130_cpu/candidate/render_receipt.json'),('report_residential_finalization.py',B/'dual_unit_residential_floor_03/finalization/finalization_plan.json'),('report_wood115_matched.py',B/'commercial_office_floor_02/wood115_review/evidence.json'),('report_bathroom132.py',B/'dual_unit_residential_floor_03/bathroom_door132_build.json'),('report_entry133.py',B/'dual_unit_residential_floor_03/entry_batch133_build.json'),('report_portal132_diagnosis.py',B/'dual_unit_residential_floor_03/portal132_diagnosis/diagnosis.json'),('index_report.py',B/'scene_slots.json')]:
 if not required.exists():runs.append({'script':script,'phase':'not_applicable','missing_input':str(required)});continue
 result=subprocess.run([sys.executable,str(T/script)],cwd=R,capture_output=True,text=True);runs.append({'script':script,'exit_code':result.returncode,'output':result.stdout[-1200:],'error':result.stderr[-1200:]});assert result.returncode==0,runs[-1]
for p,h in before.items():assert sha(Path(p))==h,('Authoritative state changed by view refresh',p)
assert json.loads((B/'scene_slots.json').read_text())['slots'][0]==approved
for p,stats in blend_stats.items():assert (Path(p).stat().st_size,Path(p).stat().st_mtime_ns)==stats,('Candidate changed',p)
for p in outputs:
 if p.suffix=='.html' and p.exists():assert p.stat().st_size<50000,(p,p.stat().st_size)
receipt=B/'report_refresh_receipt.json';a=json.loads(receipt.read_text()) if receipt.exists() else {};a.update(last_view_refresh_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),view_refresh_archive=str(archive),agent_scenes_count=len(registry),authoritative_state_hashes_unchanged=True,candidate_file_stats_unchanged=True,approved_PH_slot_unchanged=True,view_refresh_runs=runs,view_refresh_scope='Current source-bound view documents only. No metadata reset, historical review rewrite, render/GPU launch or promotion.');receipt.write_text(json.dumps(a,ensure_ascii=False,indent=2)+'\n');print('CURRENT_VIEWS_REFRESHED',len(registry),'scenes;',len(runs),'view generators;authoritative state preserved;archive',archive)
