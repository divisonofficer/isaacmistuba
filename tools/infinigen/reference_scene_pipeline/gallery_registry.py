"""Persistent reference-scene registrations consumed by the normal gallery builder."""
import copy,json,os,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
REGISTRY=ROOT/'data/venue_refs/floor_plans_v3/gallery_entries.json'
IDS={'REF_OFFICE_02','REF_DUAL_03'}
def load_entries(path=REGISTRY):
 if not path.exists():return []
 rows=json.loads(path.read_text())['scenes'];ids=[r['id'] for r in rows]
 assert len(ids)==len(set(ids)) and set(ids)<=IDS,'Invalid reference registry IDs'
 for row in rows:
  assert row['paths'].get('blend') and Path(row['paths']['blend']).is_file(),row['id']
 return rows
def merge_entries(rows,path=REGISTRY,output_dir=None):
 entries=load_entries(path)
 if output_dir is not None:
  canonical=ROOT/'out/scene_gallery/infinigen_2.2';output_dir=Path(output_dir)
  if output_dir.resolve()!=canonical.resolve():
   for row in entries:
    for sample in row.get('samples',[]):
     relative=Path(sample);assert not relative.is_absolute() and '..' not in relative.parts
     source=canonical/relative;assert source.is_file(),source
     target=output_dir/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
 ids={r['id'] for r in entries};preserved=copy.deepcopy([r for r in rows if r['id'] not in ids]);merged=[r for r in rows if r['id'] not in ids]+entries
 assert [r for r in merged if r['id'] not in ids]==preserved
 return merged
def record_entry(row,path=REGISTRY):
 assert row['id'] in IDS
 raw=path.read_bytes() if path.exists() else None;rows=load_entries(path);rows=[r for r in rows if r['id']!=row['id']]+[row];payload=json.dumps({'schema_version':1,'scenes':rows},ensure_ascii=False,indent=2)
 assert (path.read_bytes() if path.exists() else None)==raw,'Concurrent registry modification'
 temp=path.with_name(path.name+'.tmp');temp.write_text(payload);assert (path.read_bytes() if path.exists() else None)==raw;os.replace(temp,path)
