"""Merge verified terminal batch receipts after coordinator loss; never rerender."""
import argparse,json,hashlib,shutil,os,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def terminal(pid):
 p=Path(f'/proc/{pid}/stat')
 if not p.exists():return True
 try:return p.read_text().rsplit(')',1)[1].split()[0]=='Z'
 except FileNotFoundError:return True

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--scene',choices=['office','residential'],required=True);ap.add_argument('--revision',type=int,required=True);a=ap.parse_args();scene='commercial_office_floor_02' if a.scene=='office' else 'dual_unit_residential_floor_03';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;out=ref/f'full_suite_r{a.revision}';state=out/'job.json';job=json.loads(state.read_text());assert terminal(job['pid']),'Coordinator still live;do not recover';assert all(terminal(w['pid']) for w in job['workers']),'A batch still lives;wait same process'
 sha=job['source_sha256'];assert digest(job['source'])==sha;expected=job['required_view_names'];frames={};receipts=[];merged=None
 for w in job['workers']:
  folder=out/f'batch_{w["batch"]}';rp=folder/'candidate/render_receipt.json';r=json.loads(rp.read_text());assert r['phase']=='rendered_visual_review_pending' and r['source_unchanged'] and r['source_sha256']==sha
  assert set(f['name'] for f in r['frames'])==set(w['views']);assert 'Blender quit' in (folder/'render.log').read_text()
  if merged is None:merged=dict(r)
  else:
   for k in ['renderer_sha256','lighting_policy','denoising']:assert r[k]==merged[k],k
  for f in r['frames']:
   assert f['name'] not in frames and digest(f['path'])==f['sha256'];frames[f['name']]=dict(f)
  receipts.append(str(rp))
 assert set(frames)==set(expected);candidate=out/'candidate';candidate.mkdir(exist_ok=True)
 for name in expected:
  f=frames[name];target=candidate/(name+'.png')
  if target.exists():assert digest(target)==f['sha256'],'Existing differing merged frame;refuse overwrite'
  else:shutil.copy2(f['path'],target)
  f['path']=str(target)
 assert digest(job['source'])==sha
 merged.update(frames=[frames[n] for n in expected],batch_receipts=receipts,phase='rendered_visual_review_pending',source_unchanged=True,visual_acceptance=False,recovery='All batch receipts/log endings/source andframe hashes verified after coordinator exit. Process exit codes unknown,not inferred.')
 rp=candidate/'render_receipt.json'
 if rp.exists():
  existing=json.loads(rp.read_text());assert {f['name']:f['sha256'] for f in existing['frames']}=={n:frames[n]['sha256'] for n in expected}
 else:rp.write_text(json.dumps(merged,indent=2))
 backup=out/'coordinator_state_before_recovery.json'
 if not backup.exists():backup.write_text(json.dumps(job,indent=2))
 job.update(phase=f'rendered_full{len(expected)}_visual_review_pending',rendered_view_count=len(expected),recovery_evidence={'terminal_parent_and_workers':True,'batch_receipts':receipts,'source_and_frame_hashes_verified':True,'worker_exit_codes':'unavailable_not_inferred','recovered_at':datetime.datetime.now(datetime.timezone.utc).isoformat()});state.write_text(json.dumps(job,indent=2));print('Recovered verified frames',len(expected),'no rendering orvisual acceptance',flush=True)
if __name__=='__main__':main()
