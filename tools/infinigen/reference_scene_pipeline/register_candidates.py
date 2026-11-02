"""Register two visibly unfinished candidates; never promote a dataset or alter PH."""
import base64,copy,hashlib,io,json,os,re
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[3]
REVIEW=Path('/tmp/claude-0/-jarvis-project-robomituba/2e50bd36-1d06-42cb-8d8e-829a58d12a07/scratchpad/review')
SPECS=[('REF_OFFICE_02','commercial_office_floor_02',48712502,13,14,'사무실'),('REF_DUAL_03','dual_unit_residential_floor_03',48712503,11,33,'2세대 주거층')]
def uri(p):
 with Image.open(p) as im:
  im=im.convert('RGB');im.thumbnail((640,480));b=io.BytesIO();im.save(b,'JPEG',quality=76,optimize=True)
 return 'data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode()
def upsert(rows,entries):
 ids={x['id'] for x in entries};before=copy.deepcopy([x for x in rows if x.get('id') not in ids]);out=[x for x in rows if x.get('id') not in ids]+entries
 assert [x for x in out if x.get('id') not in ids]==before;return out
def write(path,raw,value):
 assert path.read_bytes()==raw,'Concurrent modification: '+str(path)
 backup=path.with_name(path.name+'.before_ref_slots_registration');
 if not backup.exists():backup.write_bytes(raw)
 tmp=path.with_name(path.name+'.ref_slots.tmp');tmp.write_text(value);assert path.read_bytes()==raw;os.replace(tmp,path)
def main():
 manifest_path=ROOT/'out/scene_gallery/infinigen_2.2/manifest.json';galleries=[];inspections=[];receipts=[]
 for ident,scene,seed,revision,rooms,title in SPECS:
  ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;renders=ref/'renders'/f'r{revision}';receipt=json.loads((renders/'render_receipt.json').read_text());blend=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full'/f'scene_candidate_r{revision}.blend';assert receipt['source']==str(blend) and receipt['source_unchanged'];assert hashlib.sha256(blend.read_bytes()).hexdigest()==receipt['source_sha256']
  expected=13 if revision==13 else 22;assert len(receipt['frames'])==expected
  cards=[];samples=[];thumbdir=manifest_path.parent/'thumbs'/ident;thumbdir.mkdir(parents=True,exist_ok=True)
  for index,frame in enumerate(receipt['frames']):
   path=Path(frame['path']);assert path.is_file();assert hashlib.sha256(path.read_bytes()).hexdigest()==frame['sha256'];name=frame['name'];cards.append({'room':name,'critic':None,'imgs':[uri(path)],'views':[name],'gt':None,'vlm':None,'refcmp':{'round':f'r{revision}','missing':['최종 시각 검수 및 패킹 검증 미완료'],'different':['레퍼런스 대비 디테일 보완 중'],'matches':['실제 Infinigen 후보 씬 렌더']}})
   if index<6:
    out=thumbdir/(name+'.jpg')
    with Image.open(path) as im:im.convert('RGB').resize((320,240)).save(out,quality=80)
    samples.append(str(out.relative_to(manifest_path.parent)))
  paths={'blend':str(blend),'renders':str(renders),'report':str(ref/'progress.html'),'review_report':str(ref/'progress.html')}
  galleries.append({'id':ident,'kind':'floor','title':title+' · 제작/검수 중 (승격 아님)','tag':scene,'seed':seed,'round':revision,'status':'rendered','quality_status':'in_progress','rooms':rooms,'area_m2':None,'readiness':{'plan':True,'blend':True,'render':True,'gt':False,'vlm_review':False,'human_score':False,'session_visual_review':False,'visual_acceptance':False},'human':{'round':None,'avg':None,'min':None,'rooms_pass':0,'rooms_scored':0},'vlm':{'major':None,'top':{},'rooms_reviewed':0},'samples':samples,'paths':paths,'dataset':None})
  entry={'id':ident,'title':title+' · 제작/검수 중 (승격 아님)','round':f'r{revision}','F':None,'quality_status':'in_progress','rooms':cards,'desc':'실제 후보 렌더. 전체 시각 검수/최종 합격 전. 학습 데이터셋 승격 없음.','changes':{'round':f'r{revision}','what':['현재 후보와 미완료 검수 상태 공개','보고서: '+str(ref/'progress.html')]},'plan':uri(renders/'overview.png'),'room_refs':{},'refcmp_floor':{'round':f'r{revision}','missing':['최종 시각 검수 및 패킹 검증'],'different':['원본 치수는 추정'],'matches':['실제 후보 Blender 씬의 전체 평면 렌더']},'paths':paths}
  inspections.append(entry);receipts.append((ref,entry))
 from gallery_registry import record_entry
 for gallery in galleries:record_entry(gallery)
 raw=manifest_path.read_bytes();manifest=json.loads(raw);manifest['scenes']=upsert(manifest['scenes'],galleries);manifest['count']=len(manifest['scenes']);write(manifest_path,raw,json.dumps(manifest,ensure_ascii=False,indent=1))
 p=REVIEW/'data.json';raw=p.read_bytes();write(p,raw,json.dumps(upsert(json.loads(raw),inspections),ensure_ascii=False))
 p=REVIEW/'floor_review.html';raw=p.read_bytes();html=raw.decode();pattern=r'(<script\b[^>]*\bid=["\x27]data["\x27][^>]*>)(.*?)(</script>)';match=re.search(pattern,html,re.S);assert match
 rows=upsert(json.loads(match.group(2)),inspections);merged=html[:match.start()]+match.group(1)+json.dumps(rows,ensure_ascii=False).replace('</','<\\/')+match.group(3)+html[match.end():];write(p,raw,merged)
 for ref,entry in receipts:
  portable=html[:match.start()]+match.group(1)+json.dumps([entry],ensure_ascii=False).replace('</','<\\/')+match.group(3)+html[match.end():]
  __import__('lightweight_inspection').write_lightweight_inspection(ref/'inspection_candidate.html',portable)
  (ref/'registration_receipt.json').write_text(json.dumps({'scene_id':entry['id'],'quality_status':'in_progress','dataset_promoted':False,'other_scene_rows_preserved':True,'manifest':str(manifest_path),'shared_inspection':str(p),'portable_inspection':str(ref/'inspection_candidate.html')},indent=2))
 print(json.dumps({'registered':[x['id'] for x in galleries],'visual_acceptance':False,'dataset_promoted':False}))
if __name__=='__main__':main()
