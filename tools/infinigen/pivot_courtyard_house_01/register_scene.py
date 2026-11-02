"""Register only the external Pivot scene; preserve every other scene and review row."""
from pathlib import Path
import argparse,base64,copy,hashlib,io,json,os,re
from PIL import Image
ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01'
REVIEW=Path('/tmp/claude-0/-jarvis-project-robomituba/2e50bd36-1d06-42cb-8d8e-829a58d12a07/scratchpad/review')

def current():
    c=json.loads((BASE/'current_scene.json').read_text())
    assert Path(c['candidate']).is_file() and Path(c['renders']).is_dir()
    if c.get('quality_status')=='accepted':
        views=json.loads(Path(c['views']).read_text())
        expected={v['name'] for v in views}
        assert len(expected)==len(views)==c['render_count']
        assert all((Path(c['renders'])/(name+'.png')).is_file() for name in expected)
        review=json.loads((BASE/'scene_review.json').read_text())
        assert {v['space'] for v in review['findings']}==expected,'Missing final direct visual findings'
        assert Path(c['overview']).is_file() and Path(c['floorplan_asset']).is_file()
        assert hashlib.sha256(Path(c['candidate']).read_bytes()).hexdigest()==c['candidate_sha256']
    return c

def apply_gallery_entry(entry,out,thumbnailer):
    if entry.get('id')!='PH':return
    c=current();rnd=int(c['revision'].lstrip('r'));rv=Path(c['renders'])
    entry.update(round=rnd,status='rendered',title=f"Pivot 중정 주택 · {c['revision']} 세션 검수 후보 (승격 아님)",rooms=c['room_floors'])
    entry.setdefault('paths',{}).update(blend=c['candidate'],renders=c['renders'],review_report=c['report'])
    entry.setdefault('readiness',{}).update(blend=True,render=True,session_visual_review=True)
    entry['readiness']['visual_acceptance']=c.get('quality_status')=='accepted'
    if c.get('quality_status')=='accepted':
        entry['quality_status']='accepted'
        entry['title']=f"Pivot 중정 주택 · {c['revision']} 참조 검수 완료"
        entry['area_m2']=c.get('area_m2',entry.get('area_m2'))

    entry['session_review']={'mode':'session_direct_visual','external_vlm_api':False,'views_reviewed':c['render_count'],'reference_spaces':c['reference_spaces'],'report':c['report']}
    entry['samples']=['thumbs/PH/'+n for n in thumbnailer(rv,Path(out)/'thumbs/PH',6)]
    if 'rejected' in c.get('quality_status',''):
        entry.update(status='quality_rework_required',title='Pivot 중정 주택 · r21 불합격 기준본 / 재작업 중')
        entry['quality_status']=c['quality_status']
        entry['readiness']['visual_acceptance']=False


def uri(path,size=(560,420),quality=72):
    with Image.open(path) as im:
        im=im.convert('RGB');im.thumbnail(size);b=io.BytesIO();im.save(b,'JPEG',quality=quality,optimize=True)
    return 'data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode()

def inspection_entry():
    c=current();views=json.loads(Path(c['views']).read_text());review=json.loads((BASE/'scene_review.json').read_text());findings={x['space']:x for x in review['findings']}
    refs={x['id']:x for x in json.loads((BASE/'reference_manifest.json').read_text())['rooms']}
    room_by_ref={'bed1':'bedroom_0-3','bed2':'bedroom_0-2','bed3':'bedroom_0-1','bed4':'bedroom_0-0','guest_bed':'bedroom_0-4','ensuite':'bathroom_0-2','bathroom':'bathroom_0-0','wc':'bathroom_0-1','guest_bath':'bathroom_0-4','pdr':'bathroom_0-3','wir':'closet_0-0','rumpus':'living-room_0-0','dining':'dining-room_0-0','living':'living-room_0-1','kitchen':'kitchen_0-0','pantry':'utility_0-1','laundry':'utility_0-0','study':'office_0-0','entry':'hallway_0-0','garage':'garage_0-0','guest_living':'living-room_0-2','deck':'deck_0-0','courtyard':'courtyard_0-0','entry_deck':'entry-deck_0-0'}
    rooms={};room_refs={}
    for v in views:
        ref=v['reference_id'];key=v.get('room_key') or ('bathroom_0-5' if v['name'].startswith('bathroom_0-5_') else room_by_ref[ref])
        row=rooms.setdefault(key,dict(room=key,critic=None,imgs=[],views=[],gt=None,vlm=None,refcmp={'round':c['revision'],'missing':[],'different':[],'matches':['세션 직접 시각 검수 · '+refs[ref]['title']]}))
        row['imgs'].append(uri(Path(c['renders'])/(v['name']+'.png')));row['views'].append(v['name'])
        note=findings[v['name']]['awkwardness']
        for sentence in re.split(r'(?<=[.!?])\s+',note):
            bucket='different' if any(k in sentence for k in ('단순','잘림','잘려','강함','저대비','어두','부족','적음','차이','다름','근사','생략')) else 'matches'
            if sentence and sentence not in row['refcmp'][bucket]:row['refcmp'][bucket].append(sentence)
        room_refs.setdefault(key,[[uri(BASE/refs[ref]['image'],(400,300),72),refs[ref]['title']]])
    rooms['whole-house']=dict(room='whole-house',critic=None,imgs=[uri(c['overview'],(1152,1037),82)],views=['whole_house_overview'],gt=None,vlm=None,refcmp={'round':c['revision'],'missing':['원본에서 잘린 카포트'],'different':['절대 치수는 원본 스크린샷에서 추정'],'matches':[f"패킹 Blender 파일 재개방 후 {c.get('overview_dimensions',[1920,1728])[0]}×{c.get('overview_dimensions',[1920,1728])[1]} 전체 씬 평면 렌더 확인"]})
    room_refs['whole-house']=[[uri(BASE/'floorplan_v1.png',(600,660),78),'기존 생성 평면도 · 승인된 배치 변경 전 참고']]
    result={'id':'PH','title':f"Pivot 중정 주택 · {c['revision']} 세션 검수 후보 (승격 아님)",'round':c['revision'],'F':None,'rooms':list(rooms.values()),'desc':f"{c['bedrooms']}침실 · {c['room_floors']}바닥 구획 · {c['reference_spaces']}참조 공간 · 실내/외부{len(views)}뷰 직접 검수 + 전체 평면1뷰. 외부 VLM API·수치 점수 없음. 절대 치수 추정.",'changes':{'round':c['revision'],'date':'10-22','what':['침구 돌출·세탁기 원형부·WC 조명·가구 접지·옷장 측판/옷 겹침 수정',f"전체{len(views)}뷰 직접 검수 및 패킹 재개방 확인; 학습승격/GT 인증 없음",'보고서: '+c['report']]},'plan':uri(Path(c.get('floorplan_asset',BASE/'floorplan_v1.png')),(1000,1100),82),'room_refs':room_refs,'refcmp_floor':{'round':c['revision'],'missing':['원본에서 잘린 카포트','일부 사진 소품·조경 디테일'],'different':['절대 치수 추정','WIR은 원본 좁은 깊이를 유지하여 일측 수납','절차적 가구·옷·재질·식재는 사진 참조보다 단순'],'matches':['5침실 전체 주택, 데크/중정/게스트 별채 구성',f"{len(refs)}참조 공간 카메라 포함{len(views)}뷰 직접 검수",'패킹 씬 재개방 전체 평면 확인']},'paths':{'blend':c['candidate'],'renders':c['renders'],'report':c['report']},'session_review':{'views':len(views),'reference_spaces':len(refs),'mode':'session_direct_visual'}}

    if c.get('quality_status')=='accepted':
        result['title']=f"Pivot 중정 주택 · {c['revision']} 참조 검수 완료"
        result['quality_status']='accepted'
        result['changes']['what']=c.get('change_summary',result['changes']['what'])
        result['refcmp_floor']['matches'].append('네 지적 공간의 필수 시각 조건 및 영향 공간 회귀 검수 완료')
    if 'rejected' in c.get('quality_status',''):
        result['title']='Pivot 중정 주택 · r21 불합격 기준본 / 재작업 중'
        result['quality_status']='quality_rework_required'
        result['desc']='사용자 지적으로 r21 품질 합격 철회. 표시 이미지는 보존한 r21 기준본이며 새 배치 재작업은 보고서에서 확인합니다. 최종 합격 전입니다.'
        result['refcmp_floor']['missing'].insert(0,'중정 통유리/식재, 팬트리/차고 수납, 현관 데크 레퍼런스 품질 미달')
        result['changes']['what'].insert(0,'사용자 불합격 판정: 현재 배치·가구·조경 재작업 중. r21은 비교 기준본으로만 보존.')
    return result


def replace_ph(rows,entry):
    before=[copy.deepcopy(x) for x in rows if x.get('id')!='PH'];assert sum(x.get('id')=='PH' for x in rows)==1
    result=[entry if x.get('id')=='PH' else x for x in rows]
    assert [x for x in result if x.get('id')!='PH']==before
    return result

def cas_write(path,before,text):
    assert path.read_bytes()==before,'Concurrent modification: '+str(path)
    revision=current()['revision']
    backup=path.with_name(path.name+'.pre_codex_ph_'+revision)
    if not backup.exists():backup.write_bytes(before)
    tmp=path.with_name(path.name+'.codex_ph_'+revision+'.tmp');tmp.write_text(text);assert path.read_bytes()==before,'Concurrent modification before replace: '+str(path);os.replace(tmp,path)

def register_local():
    import sys
    sys.path.insert(0,str(ROOT/'tools/infinigen'))
    from build_scene_gallery import thumbs
    c=current();entry=inspection_entry();mp=ROOT/'out/scene_gallery/infinigen_2.2/manifest.json';raw=mp.read_bytes();m=json.loads(raw);ph=copy.deepcopy(next(x for x in m['scenes'] if x['id']=='PH'));apply_gallery_entry(ph,mp.parent,thumbs);m['scenes']=replace_ph(m['scenes'],ph);cas_write(mp,raw,json.dumps(m,ensure_ascii=False,indent=1)+'\n')
    p=REVIEW/'data.json';raw=p.read_bytes();rows=replace_ph(json.loads(raw),entry);cas_write(p,raw,json.dumps(rows,ensure_ascii=False))
    p=REVIEW/'floor_review.html';raw=p.read_bytes();s=raw.decode();pattern=r'(<script\b[^>]*\bid=[\"\x27]data[\"\x27][^>]*>)(.*?)(</script>)';match=re.search(pattern,s,flags=re.S);assert match,'Embedded review data not found';rows=replace_ph(json.loads(match.group(2)),entry);replacement=match.group(1)+json.dumps(rows,ensure_ascii=False).replace('</','<\\/')+match.group(3);s=s[:match.start()]+replacement+s[match.end():];cas_write(p,raw,s)
    (BASE/('inspection_entry_'+c['revision']+'.json')).write_text(json.dumps(entry,ensure_ascii=False))
    portable=Path(c['local_inspection']);tmp=portable.with_name(portable.name+'.tmp');tmp.write_bytes(p.read_bytes());os.replace(tmp,portable)
    receipt={'dataset_round':ph['round'],'dataset_blend':ph['paths']['blend'],'inspection_round':entry['round'],'inspection_cards':len(entry['rooms']),'inspection_images':sum(len(r['imgs']) for r in entry['rooms']),'review_html':str(p),'portable_inspection':str(portable),'candidate_sha256':c['candidate_sha256'],'other_scene_rows_unchanged':True}
    (BASE/('registration_receipt_'+c['revision']+'.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':register_local()
