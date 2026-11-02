"""CPU-only two-shard fixed-view rendering with verified receipt merge."""
import argparse,concurrent.futures,hashlib,json,os,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);p.add_argument('--revision',type=int);p.add_argument('--blend',type=Path);p.add_argument('--views',type=Path);a=p.parse_args()
office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';rev=f'r{a.revision}' if a.revision else ('r13' if office else 'r11');seed=48712502 if office else 48712503
ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';source=a.blend.resolve() if a.blend else base/f'scene_candidate_{rev}.blend';views=a.views.resolve() if a.views else base/('review_views_r5.json' if office else 'review_views_r9.json');records=json.loads(views.read_text());out=ref/'renders'/rev
assert not out.exists(),'Completed round already exists; inspect existing receipt rather than overwrite'
source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
def worker(index):
 shard=ref/'render_shards'/f'{rev}_{index}';shard.mkdir(parents=True,exist_ok=True)
 wanted=[x['name'] for x in records[index::2]];existing={}
 for path in sorted(shard.rglob('render_receipt.json')):
  record=json.loads(path.read_text());assert record['source_sha256']==source_hash
  for frame in record['frames']:
   assert hashlib.sha256(Path(frame['path']).read_bytes()).hexdigest()==frame['sha256'];existing[frame['name']]=frame
 pending=[name for name in wanted if name not in existing]
 if pending:
  target=shard if not (shard/'render_receipt.json').exists() else shard/('continuation_'+str(len(list(shard.glob('continuation_*')))+1))
  target.mkdir(parents=True,exist_ok=True)
  cmd=['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background',str(source),'--python-exit-code','1','--python',str(Path(__file__).with_name('render.py')),'--','--views',str(views),'--out',str(target),'--names',','.join(pending),'--width','1024' if office else '800','--samples','32' if office else '24','--overview-width','2048']
  env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=''
  with (target/'render.log').open('w') as log:subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,cwd=ROOT)
  record=json.loads((target/'render_receipt.json').read_text());assert record['source_sha256']==source_hash and record['source_unchanged']
  for frame in record['frames']:existing[frame['name']]=frame
 else:record=json.loads((shard/'render_receipt.json').read_text())
 assert set(wanted)==set(existing)
 record['frames']=[existing[name] for name in wanted];record['source_unchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==source_hash
 return record
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:receipts=list(pool.map(worker,[0,1]))
frames=[f for receipt in receipts for f in receipt['frames']];assert len(frames)==len(records);assert {f['name'] for f in frames}=={x['name'] for x in records}
out.mkdir(parents=True);merged=dict(receipts[0]);merged['frames']=[]
for record in records:
 frame=next(f for f in frames if f['name']==record['name']);dest=out/Path(frame['path']).name;shutil.copy2(frame['path'],dest);assert hashlib.sha256(dest.read_bytes()).hexdigest()==frame['sha256'];frame['path']=str(dest);merged['frames'].append(frame)
merged['source_unchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==source_hash;assert merged['source_unchanged'];merged['phase']='rendered_visual_review_pending';merged['shard_receipts']=[str(ref/'render_shards'/f'{rev}_{i}'/'render_receipt.json') for i in range(2)]
(out/'render_receipt.json').write_text(json.dumps(merged,indent=2));print(json.dumps({'scene':scene,'revision':rev,'frames':len(frames),'visual_acceptance':False}),flush=True)
