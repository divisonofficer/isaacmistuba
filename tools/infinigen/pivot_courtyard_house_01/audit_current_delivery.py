"""Verify final source/render/review/packed-scene/registry agreement from actual files."""
import datetime,hashlib,json,re
from pathlib import Path
from PIL import Image

R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
c=json.loads((B/'current_scene.json').read_text());checks={};details={}
def check(name,value):checks[name]=bool(value)
def read(path):return json.loads(Path(path).read_text())
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()
check('canonical_visual_acceptance',c.get('quality_status')=='accepted')
candidate=Path(c['candidate']);candidate_sha=sha(candidate);pack=read(candidate.with_suffix('.audit.json'))
check('actual_packed_candidate_hash',candidate_sha==c.get('candidate_sha256')==pack.get('candidate_sha256'))
check('stable_alias_exact_candidate',Path(c['stable_candidate']).resolve()==candidate.resolve())
check('packed_visual_review_complete',pack.get('visual_accepted') and pack.get('complete_direct_review_verified'))
check('packed_geometry_images_valid',not any(pack.get(k) for k in ['invalid_mesh_dimensions','nonfinite_vertex_meshes','invalid_object_transforms','invalid_curve_objects','missing_external_images']))
plan=read(c['authored_plan']);check('actual_floor_program',pack['room_floor_count']==len(plan['rooms'])==c['room_floors'] and set(pack['expected_floor_names'])=={n+'.floor' for n in plan['rooms']})
check('five_single_bedroom_families',len(pack['bedrooms'])==c['bedrooms']==5 and all(len(v)==1 for v in pack['bedrooms'].values()))
progress=read(B/'full_rework_render_progress.json');review=read(c['visual_review_record']);views=read(c['views']);names={v['name'] for v in views};findings=review['findings'];by={v['space']:v for v in findings};frames={v['name']:v for v in progress['completed']}
check('render_review_source_exact',progress['source_sha256']==review['source_sha256']==pack['source_sha256'])
check('complete_camera_and_review_coverage',len(views)==len(names)==len(findings)==len(frames)==c['render_count'] and names==set(by)==set(frames))
check('all_direct_review_verdicts_pass',review['status']=='all_views_accepted' and all(v.get('view_verdict') in ('pass','regression_pass') for v in findings))
images=[]
for name in sorted(names):
    path=Path(c['renders'])/(name+'.png');digest=sha(path)
    with Image.open(path) as im:size=list(im.size)
    images.append({'view':name,'sha256':digest,'dimensions':size,'verified':digest==by.get(name,{}).get('render_sha256')==frames.get(name,{}).get('sha256') and size==[1024,768]})
check('actual_final_images_match_render_and_direct_review',all(v['verified'] for v in images))
quality=read(B/'quality_acceptance_v2.json');check('all_explicit_space_conditions',quality['status']=='accepted' and all(g['status']=='pass' and g.get('evidence') for v in quality['views'].values() for g in v['mandatory_gates']))
global_results=quality.get('global_gate_results',[]);check('all_global_requirements_have_evidence',len(global_results)==len(quality['global_gates']) and all(v.get('status')=='pass' and v.get('evidence') for v in global_results))
physical=read(c['physical_audit']);check('current_physical_audit_pass',physical['status']=='pass' and Path(physical['source_scene']).resolve()==Path(progress['source_scene']).resolve())
with Image.open(c['overview']) as im:size=list(im.size)
ov=read(c['overview_provenance']);check('overview_from_actual_final_packed_file',ov['source_sha256']==candidate_sha and Path(ov['source_packed_scene']).resolve()==candidate.resolve() and ov['render_sha256']==sha(c['overview']) and size==c['overview_dimensions'])
with Image.open(c['floorplan_asset']) as im:plan_size=list(im.size)
check('current_high_resolution_plan_asset',plan_size==[4096,3072])
gallery=read(R/'out/scene_gallery/infinigen_2.2/manifest.json');ph=next(v for v in gallery['scenes'] if v['id']=='PH')
check('actual_dataset_registration',ph['round']==int(c['revision'].lstrip('r')) and ph.get('quality_status')=='accepted' and ph['paths']['blend']==c['candidate'] and ph['paths']['renders']==c['renders'] and ph['readiness']['visual_acceptance'])
inspection=Path(c['local_inspection']).read_text();match=re.search(r'<script\b[^>]*\bid=["\x27]data["\x27][^>]*>(.*?)</script>',inspection,re.S);rows=json.loads(match.group(1)) if match else [];entry=next((v for v in rows if v.get('id')=='PH'),{})
check('actual_local_inspection_registration',entry.get('round')==c['revision'] and entry.get('quality_status')=='accepted' and entry.get('paths',{}).get('blend')==c['candidate'] and entry.get('paths',{}).get('renders')==c['renders'])
inspection_views=[v for room in entry.get('rooms',[]) for v in room['views']];check('inspection_contains_every_view_and_overview',set(inspection_views)==names|{'whole_house_overview'} and len(inspection_views)==len(names)+1 and all(len(room['imgs'])==len(room['views']) for room in entry.get('rooms',[])))
report=Path(c['report']).read_text();check('tabbed_report_links_current_candidate_and_plan','TABBED_PROGRESS_V1' in report and candidate.name in report and Path(c['floorplan_asset']).name in report)
report_ui=read(B/'report_browser_final_r39.json');inspection_ui=read(B/'inspection_browser_r39.json')
check('actual_report_browser_check_matches_file',report_ui['all_checks_pass'] and report_ui['report_sha256']==sha(c['report']))
check('actual_inspection_browser_check_matches_file',inspection_ui['all_checks_pass'] and inspection_ui['inspection_sha256']==sha(c['local_inspection']))
result={'scene_id':c['scene_id'],'revision':c['revision'],'audited_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'checks':checks,'all_checks_pass':all(checks.values()),'images':images,'candidate_sha256':candidate_sha,'scope_notice':'Artifact hashes/coverage verify consistency, not aesthetic quality. Direct visual findings and explicit criterion evidence are separate required inputs. No navigation-training or sensor-GT promotion is certified.'}
out=B/('delivery_audit_'+c['revision']+'.json');out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'revision':c['revision'],'checks':checks,'all_checks_pass':result['all_checks_pass']},ensure_ascii=False))
assert result['all_checks_pass'],'Final delivery consistency audit failed; inspect actual evidence before claiming completion'
