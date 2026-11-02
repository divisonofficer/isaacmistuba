"""Reuse completed source-bound frames from terminal oractive per-frame receipts.
No parent completion is inferred andno rendering is performed.
"""
import argparse,json,hashlib,shutil,time
from pathlib import Path

def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,required=True);p.add_argument('--names',required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--views',type=Path,required=True);a=p.parse_args();assert not a.out.exists();names=a.names.split(',');assert len(set(names))==len(names)
 for attempt in range(5):
  try:raw=a.receipt.read_bytes();r=json.loads(raw);break
  except json.JSONDecodeError:
   if attempt==4:raise
   time.sleep(.05)
 frames={f['name']:f for f in r['frames']};assert set(names)<=set(frames),'Requested frames notyet receipted;observe same parent,do not rerender';assert digest(r['source'])==r['source_sha256'];views={v['name']:v for v in json.loads(a.views.read_text())}
 for name in names:
  f=frames[name];assert digest(f['path'])==f['sha256'];v=views[name];expected={**v,'render_width':2048 if v.get('overview') else 1280,'samples':48};assert f['camera']==expected,(name,'camera mismatch')
 a.out.mkdir(parents=True);subset=[]
 for name in names:
  f=dict(frames[name]);target=a.out/(name+'.png');shutil.copy2(f['path'],target);assert digest(target)==f['sha256'];f['path']=str(target.resolve());subset.append(f)
 result=dict(r);result.update(frames=subset,phase='rendered_subset_visual_review_pending',source_unchanged=True,visual_acceptance=False,cache_subset_only=True,parent_receipt=str(a.receipt.resolve()),parent_receipt_snapshot_sha256=hashlib.sha256(raw).hexdigest(),parent_completion_inferred=False);(a.out/'parent_receipt_at_extraction.json').write_bytes(raw);(a.out/'render_receipt.json').write_text(json.dumps(result,indent=2));print('Extracted verified cached frames',len(subset),'parent completion notinferred',flush=True)
if __name__=='__main__':main()
