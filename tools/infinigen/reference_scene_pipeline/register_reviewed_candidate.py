"""Publish session-reviewed candidates to existing gallery/inspection, without promotion."""
import argparse,hashlib,json,re,io,base64
from pathlib import Path
from PIL import Image
from register_candidates import ROOT,REVIEW,uri,upsert,write
p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);p.add_argument('--revision',type=int,required=True);p.add_argument('--views',type=Path);p.add_argument('--validate-only',action='store_true');a=p.parse_args();office=a.scene=='office';ident,scene,rooms,title=('REF_OFFICE_02','commercial_office_floor_02',14,'사무실') if office else ('REF_DUAL_03','dual_unit_residential_floor_03',33,'2세대 주거층');ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;revision=a.revision;renders=ref/'renders'/f'r{revision}';receipt=json.loads((renders/'render_receipt.json').read_text());review_path=ref/f'delivery_visual_review_r{revision}.json';review=json.loads(review_path.read_text());assert review['ready_for_user_review'] and review['session_visual_acceptance'] and not review['dataset_promoted'];assert review['source_sha256']==receipt['source_sha256'];blend=Path(receipt['source']);assert hashlib.sha256(blend.read_bytes()).hexdigest()==receipt['source_sha256'];assert receipt['source_unchanged'];from review_frame_coverage import validate_frame_coverage
views_path=a.views or blend.parent/f'review_views_delivery_r{revision}.json'
if not views_path.is_file():raise ValueError('Missing intended camera manifest;provide --views explicitly')
full_requirements=json.loads((ROOT/'data/venue_refs/floor_plans_v3/fine_goal_requirements.json').read_text())['full_view_requirements'][scene]
required_names=full_requirements['required_view_names']
assert len(required_names)>=full_requirements['minimum_views']
view_count=validate_frame_coverage(json.loads(views_path.read_text()),receipt,review,required_names)
if a.validate_only:
 print(json.dumps({'status':'preflight_only_no_registry_changes','view_count':view_count,'source_sha256':receipt['source_sha256'],'views':str(views_path)}));raise SystemExit(0)
manifest_path=ROOT/'out/scene_gallery/infinigen_2.2/manifest.json';cards=[];samples=[];thumbdir=manifest_path.parent/'thumbs'/ident/f'r{revision}';thumbdir.mkdir(parents=True,exist_ok=True)
for i,frame in enumerate(receipt['frames']):
 path=Path(frame['path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==frame['sha256'];name=frame['name'];cards.append({'room':name,'critic':None,'imgs':[uri(path)],'views':[name],'gt':None,'vlm':None,'refcmp':{'round':f'r{revision}','missing':[],'different':review['reference_comparison']['differences'],'matches':review['reference_comparison']['matches']}})
 if i<6:
  dest=thumbdir/(name+'.jpg')
  with Image.open(path) as im:im.convert('RGB').resize((320,240)).save(dest,quality=80)
  samples.append(str(dest.relative_to(manifest_path.parent)))
paths={'views':str(views_path),'blend':str(blend),'renders':str(renders),'report':str(ref/'progress.html'),'review_report':str(review_path),'inspection':str(ref/'inspection_candidate.html')}
gallery={'id':ident,'kind':'floor','title':title+' · 세션 검수 완료 / 사용자 검토 대기','tag':scene,'seed':48712502 if office else 48712503,'round':revision,'status':'rendered','quality_status':'session_reviewed','rooms':rooms,'area_m2':None,'readiness':{'plan':True,'blend':True,'render':True,'gt':False,'vlm_review':False,'human_score':False,'session_visual_review':True,'visual_acceptance':True,'user_approved':False},'human':{'round':None,'avg':None,'min':None,'rooms_pass':0,'rooms_scored':0},'vlm':{'major':None,'top':{},'rooms_reviewed':0},'samples':samples,'paths':paths,'dataset':None,'dataset_promoted':False}
entry={'id':ident,'title':gallery['title'],'round':f'r{revision}','F':None,'quality_status':'session_reviewed','rooms':cards,'desc':f'실제 패킹 씬의 {len(cards)}개 뷰를 이 세션에서 직접 검수. 사용자 승인/데이터셋 승격 없음. 정량 VLM 점수·사람 점수는 미기입.','changes':{'round':f'r{revision}','what':['다중 스케일 재질, 실제 지원·동선 검사, 전체 뷰 직접 검수','검수 근거: '+str(review_path)]},'plan':uri(renders/'overview.png'),'room_refs':{},'refcmp_floor':{'round':f'r{revision}','missing':[],'different':review['reference_comparison']['differences'],'matches':review['reference_comparison']['matches']},'paths':paths,'dataset_promoted':False,'user_approved':False}
# Persist the canonical inspection entry for the owner's recurring importer.
refcache={}
def reference_uri(path):
 if path not in refcache:
  with Image.open(path) as im:
   im=im.convert('RGB');im.thumbnail((320,240));buffer=io.BytesIO();im.save(buffer,'JPEG',quality=66,optimize=True)
  refcache[path]='data:image/jpeg;base64,'+base64.b64encode(buffer.getvalue()).decode()
 return refcache[path]
for card in cards:
 name=card['room']
 if office:
  role='open_workplace' if name.startswith('open_workplace') else 'conference' if name.startswith(('conference','meeting_')) else 'private_office' if name=='private_office' else 'reception' if name=='reception' else 'breakout_kitchen' if name.startswith(('breakout','library_')) else None
 else:
  role='living' if any(k in name for k in ('living','sofa')) else 'bedroom' if any(k in name for k in ('master','bedroom')) else 'bathroom' if any(k in name for k in ('bathroom','wetroom')) else None
 reference=ref/(role+'_reference_v1.png') if role else ref/'source.png'
 if name=='overview':reference=ref/('floorplan_reference_v3.png' if office else 'floorplan_reference_v1.png')
 if reference.exists():entry['room_refs'][name]=[[reference_uri(reference),'제공 원본 / 채택된 스타일 레퍼런스 · 구조 치수의 증거 아님']]
entry['review_views_sha256']=hashlib.sha256(views_path.read_bytes()).hexdigest();entry['source_sha256']=receipt['source_sha256'];entry['session_visual_review']=True
(ref/'inspection_entry.json').write_text(json.dumps(entry,ensure_ascii=False))
from gallery_registry import record_entry
record_entry(gallery)
raw=manifest_path.read_bytes();manifest=json.loads(raw);manifest['scenes']=upsert(manifest['scenes'],[gallery]);manifest['count']=len(manifest['scenes']);write(manifest_path,raw,json.dumps(manifest,ensure_ascii=False,indent=1))
p=REVIEW/'data.json';raw=p.read_bytes();write(p,raw,json.dumps(upsert(json.loads(raw),[entry]),ensure_ascii=False))
p=REVIEW/'floor_review.html';raw=p.read_bytes();html=raw.decode();pattern=r'(<script\b[^>]*\bid=["\x27]data["\x27][^>]*>)(.*?)(</script>)';match=re.search(pattern,html,re.S);assert match
rows=upsert(json.loads(match.group(2)),[entry]);encode=lambda value:json.dumps(value,ensure_ascii=False).replace('</','<\\/');merged=html[:match.start()]+match.group(1)+encode(rows)+match.group(3)+html[match.end():];write(p,raw,merged)
portable=html[:match.start()]+match.group(1)+encode([entry])+match.group(3)+html[match.end():];__import__('lightweight_inspection').write_lightweight_inspection(ref/'inspection_candidate.html',portable)
for path,key in [(manifest_path,'scenes'),(REVIEW/'data.json',None)]:
 rows=json.loads(path.read_text());rows=rows[key] if key else rows;found=[r for r in rows if r.get('id')==ident];assert len(found)==1 and found[0]['quality_status']=='session_reviewed'
record={'scene_id':ident,'revision':revision,'quality_status':'session_reviewed','dataset_promoted':False,'user_approved':False,'source_sha256':receipt['source_sha256'],'frame_count':len(cards),'other_scene_rows_preserved':True,'manifest':str(manifest_path),'shared_inspection':str(p),'portable_inspection':str(ref/'inspection_candidate.html'),'browser_verification_pending':True};(ref/'registration_receipt.json').write_text(json.dumps(record,indent=2));print(json.dumps(record))
