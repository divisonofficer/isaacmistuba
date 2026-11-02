"""Activate only the fully reviewed Pivot r39 artifacts; preserve other scene rows."""
import copy,datetime,hashlib,json,os,shutil,sys
from pathlib import Path
from PIL import Image

R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
def read(path):return json.loads(Path(path).read_text())
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
def save(path,data,before=None):
    if before is not None:assert path.read_bytes()==before,'Concurrent edit: '+str(path)
    tmp=path.with_name(path.name+'.r39.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    if before is not None:assert path.read_bytes()==before,'Concurrent edit before replace: '+str(path)
    tmp.replace(path)
c=read(B/'current_scene_r39.pending.json');candidate=Path(c['candidate']);digest=sha(candidate);pack=read(candidate.with_suffix('.audit.json'));review=read(c['visual_review_record']);quality=read(B/'quality_acceptance_v2.json');views=read(c['views']);names={v['name'] for v in views}
assert c['revision']=='r39' and digest==c['candidate_sha256']==pack['candidate_sha256']
assert pack['visual_accepted'] and pack['complete_direct_review_verified'] and pack['source_sha256']==review['source_sha256']
assert review['status']=='all_views_accepted' and len(review['findings'])==len(names)==c['render_count']==38 and {v['space'] for v in review['findings']}==names
assert all(v['view_verdict'] in ('pass','regression_pass') for v in review['findings'])
assert quality['visual_review_status']=='accepted' and all(g['status']=='pass' and g.get('evidence') for v in quality['views'].values() for g in v['mandatory_gates'])
physical=read(c['physical_audit']);assert physical['status']=='pass' and physical['rooms']==c['room_floors']==29 and physical['bedrooms']==c['bedrooms']==5
for v in review['findings']:
    path=Path(c['renders'])/(v['space']+'.png');assert sha(path)==v['render_sha256']
overview=Path(c['overview']);provenance=read(c['overview_provenance']);manual=read(B/'final_overview_review_r39.json');job=read(B/'final_overview_job_r39.json')
assert job['phase']=='complete' and job['source_sha256']==digest and job['png_fully_decoded']
assert provenance['source_sha256']==digest==manual['source_packed_sha256']
assert manual['status']=='pass' and sha(overview)==manual['render_sha256']==provenance['render_sha256']
with Image.open(overview) as im:im.load();assert list(im.size)==c['overview_dimensions']==[3840,2560]
assert Path(c['floorplan_asset']).is_file()

current_path=B/'current_scene.json';old_raw=current_path.read_bytes();old=json.loads(old_raw)
for path in [current_path,B/'scene_review.json']:
    backup=path.with_name(path.stem+'.before_r39'+path.suffix)
    if not backup.exists():shutil.copy2(path,backup)
latest=Path(c['stable_candidate']);old_target=os.readlink(latest) if latest.is_symlink() else None
if latest.exists():assert sha(latest) in (old['candidate_sha256'],digest),'Stable file changed outside this operation'
if latest.exists() and not latest.is_symlink():
    backup=latest.with_name(latest.stem+'.before_r39.blend')
    if not backup.exists():shutil.copy2(latest,backup)
link=latest.with_name(latest.name+'.r39.tmp')
if link.is_symlink():link.unlink()
os.symlink(candidate.name,link);os.replace(link,latest)
now=datetime.datetime.now(datetime.timezone.utc).isoformat();c.pop('_draft_notice',None);c.update(quality_status='accepted',updated_at=now,visual_review='All38 actual final-source views directly inspected plus final packed-file overview directly inspected.',system_registration='Local registration transaction starting; browser/final consistency audit pending.',public_link_refresh='Existing public artifact not republished in this session. Local report and inspection are authoritative; final paths will be sent to CLAUDE.')
canonical_review={**review,'revision':'r39','candidate':str(candidate),'candidate_sha256':digest,'overview_review':'final_overview_review_r39.json'}
save(B/'scene_review.json',canonical_review);save(current_path,c,old_raw)
sys.path.insert(0,str(Path(__file__).parent));from register_scene import register_local
register_local()
slots_path=B.parent/'scene_slots.json';raw=slots_path.read_bytes();slots=json.loads(raw);others=copy.deepcopy([v for v in slots['slots'] if v['scene_id']!=c['scene_id']]);matches=[v for v in slots['slots'] if v['scene_id']==c['scene_id']];assert len(matches)==1
matches[0].update(status='accepted',revision='r39',blend=str(candidate),render_count=38,overview=str(overview),report=c['report'],inspection=c['local_inspection'],updated_at=now)
assert [v for v in slots['slots'] if v['scene_id']!=c['scene_id']]==others;save(slots_path,slots,raw)
c['system_registration']='PH r39 dataset and portable local inspection registered; browser and final consistency audit pending.';save(current_path,c)
receipt={'phase':'registered_browser_and_final_audit_pending','revision':'r39','candidate_sha256':digest,'previous_revision':old['revision'],'previous_stable_target':old_target,'inspection':c['local_inspection'],'report':c['report'],'other_scene_slots_preserved':True,'activated_at':now}
save(B/'activation_receipt_r39.json',receipt);print('PIVOT_R39_REGISTERED_BROWSER_CHECK_PENDING',json.dumps(receipt),flush=True)
