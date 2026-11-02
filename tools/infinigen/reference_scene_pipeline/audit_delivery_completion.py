"""Requirement-by-requirement evidence audit for these two reference deliveries."""
import hashlib,json,re,datetime
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[3];B=ROOT/'data/venue_refs/floor_plans_v3';R=Path('/tmp/claude-0/-jarvis-project-robomituba/2e50bd36-1d06-42cb-8d8e-829a58d12a07/scratchpad/review');checks=[]
def js(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(name,good,evidence):checks.append({'requirement':name,'pass':bool(good),'evidence':evidence})
slots=js(B/'scene_slots.json')['slots'];gallery=js(ROOT/'out/scene_gallery/infinigen_2.2/manifest.json')['scenes'];shared=js(R/'data.json');html=(R/'floor_review.html').read_text();embedded=json.loads(re.search(r'<script[^>]*id=["\x27]data["\x27][^>]*>(.*?)</script>',html,re.S).group(1));registry=js(B/'gallery_entries.json')['scenes']
for scene,rev,count,ident,seed,refnames in [('commercial_office_floor_02',18,15,'REF_OFFICE_02',48712502,['open_workplace','conference','private_office','reception','breakout_kitchen']),('dual_unit_residential_floor_03',22,36,'REF_DUAL_03',48712503,['living','bedroom','bathroom'])]:
 ref=B/scene;work=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}';receipt=js(ref/f'renders/r{rev}/render_receipt.json');review=js(ref/f'delivery_visual_review_r{rev}.json');pack=js(ref/f'packaging_r{rev}.json');blend=Path(receipt['source']);digest=sha(blend)
 generation=js(work/'generation_state.json');check(scene+': native Infinigen generation',generation['returncode']==0 and generation['scene_exists'] and generation['plan_sha256']==sha(ref/'floor_plan.json'),str(work/'generation_state.json'))
 check(scene+': original reference and generated room assets',(ref/'source.png').is_file() and all((ref/(n+'_reference_v1.png')).is_file() for n in refnames),[str(ref/(n+'_reference_v1.png')) for n in refnames])
 plan=ref/('floorplan_reference_v3.png' if rev==18 else 'floorplan_reference_v1.png');plan_record=js(ref/'plan_asset_review.json')[plan.name];check(scene+': generated high-resolution plan',min(Image.open(plan).size)>=1024 and plan_record['status'].startswith('accepted'),str(plan))
 check(scene+': self-contained packed 3D source',digest==receipt['source_sha256']==review['source_sha256']==pack['packed_sha256'] and not pack['missing_used_images'] and pack.get('linked_libraries',0)==0 and not pack['reopen_render_pending'],str(blend))
 check(scene+': all required current-source renders',len(receipt['frames'])==count and receipt['source_unchanged'] and all(sha(Path(f['path']))==f['sha256'] for f in receipt['frames']),str(ref/f'renders/r{rev}/render_receipt.json'))
 overview=next(f for f in receipt['frames'] if f['name']=='overview');check(scene+': high-resolution native overhead',Image.open(overview['path']).size==(2048,1536),overview['path'])
 check(scene+': direct reference/awkwardness visual review',review['session_visual_acceptance'] and review['ready_for_user_review'] and review['reviewed_frame_count']==count and set(review['frames_reviewed'])=={f['name'] for f in receipt['frames']} and not review['major_unresolved_defects'],str(ref/f'delivery_visual_review_r{rev}.json'))
 for name in review['audits']:
  path=Path(name);path=path if path.is_absolute() else ref/path;d=js(path);good=d['source_sha256']==digest and not d.get('errors') and not d.get('failures') and d.get('all_pass',True);check(scene+': '+path.stem,good,str(path))
 report=(ref/'progress.html').read_text();status=js(ref/'pipeline_status.json');check(scene+': tabbed report with current final state',report.count('role="tab"')==5 and status['visual_acceptance'] and status['phase']=='session_reviewed_user_promotion_pending' and f'renders/r{rev}/overview.png' in report,str(ref/'progress.html'))
 for label,rows in [('gallery',gallery),('shared inspection data',shared),('shared rendered inspection',embedded),('persistent gallery registry',registry)]:
  matches=[x for x in rows if x['id']==ident];good=len(matches)==1
  if good:
   row=matches[0];good=row.get('quality_status')=='session_reviewed' and str(row['round']).lstrip('r')==str(rev) and row['paths']['blend']==str(blend) and not row.get('dataset_promoted')
   if label.startswith('shared'):good=good and len(row['rooms'])==count and len(row['room_refs'])==count
  check(scene+': '+label,good,ident)
 registered=js(ref/'registration_receipt.json');check(scene+': actual browser verification',not registered['browser_verification_pending'] and registered['browser_verification']['packed_path'],str(ref/'registration_receipt.json'))
 check(scene+': GPU allocation boundary',receipt['device']=='CPU' and receipt['cuda_visible_devices']=='',str(ref/f'renders/r{rev}/render_receipt.json'))
 check(scene+': user promotion boundary',not review['user_approved'] and not review['dataset_promoted'] and next(s for s in slots if s['scene_id']==scene)['user_approved'] is False,str(ref/f'delivery_visual_review_r{rev}.json'))
ph=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full/scene_passed_r39.blend';phsha=sha(ph);check('Protected PH r39 unchanged',phsha=='855f739323f17358fa442f43bf5f7c8a75cd871ba96fda6e6daca59fb23439ca',str(ph))
for name in ['gallery_rebuild_verification.json','inspection_import_verification.json']:
 d=js(B/name);good=d.get('both_scenes_survive_normal_rebuild',d.get('both_reviewed_packed_sources_retained',False));check('Owner pipeline persistence: '+name,good,str(B/name))
handoff=js(B/'orca_delivery_handoff_receipt.json');check('Orca handoff submission accepted',handoff['ok'] and handoff['result']['message']['to_handle']=='term_653a4bff-0b38-4bf7-b76b-fd50ccf99a17',str(B/'orca_delivery_handoff_receipt.json'))
check('Unified three-slot report',(B/'scene_slots.html').is_file() and (B/'scene_slots.html').read_text().count('role="tab"')==3,str(B/'scene_slots.html'))
result={'audited_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'delivery_requirements_verified' if all(x['pass'] for x in checks) else 'requirements_incomplete','requirements':checks,'failures':[x for x in checks if not x['pass']],'protected_PH_sha256':phsha,'nonblocking_limits':['User approval/dataset promotion intentionally pending and outside this delivery.','Orca message submission accepted; recipient read/acknowledgement has not been claimed. Actual owner inspection data, browser UI and recurring importer integration are verified separately.','Scene/reference/style differences and bounded physical verification limits remain explicitly recorded in final scene visual reviews.']};(B/'delivery_completion_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({'status':result['status'],'requirements':len(checks),'failures':result['failures']},ensure_ascii=False))
