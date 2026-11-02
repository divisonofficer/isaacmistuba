"""Small tabbed reports for new slots; actual state and evidence only."""
import datetime
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
SCENES=['commercial_office_floor_02','dual_unit_residential_floor_03']


def main():
    for scene in SCENES:
        ref=ROOT/'data/venue_refs/floor_plans_v3'/scene
        def read(name):
            path=ref/name
            return json.loads(path.read_text()) if path.exists() else None
        brief=read('scene_brief.json');preflight=read('preflight_layout.json')
        seed=48712502 if scene==SCENES[0] else 48712503
        work=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}'
        statepath=work/'generation_state.json'
        state=json.loads(statepath.read_text()) if statepath.exists() else None
        phase=state['phase'] if state else 'layout_analysis'
        candidates=sorted((work/'full').glob('scene_candidate_r*.blend'),key=lambda p:int(p.stem.rsplit('r',1)[1]))
        render_receipts=sorted((ref/'renders').glob('r*/render_receipt.json'),key=lambda p:int(p.parent.name[1:]))
        if candidates:phase='candidate_visual_review_in_progress'
        status={'scene_id':scene,'phase':phase,'visual_acceptance':False,
                'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'preflight_status':preflight['status'] if preflight else 'pending',
                'generation_state':str(statepath) if state else None,
                'current_candidate':str(candidates[-1]) if candidates else None,
                'remaining':['Room reference assets','Furnishing and material finish',
                    'Actual mesh/circulation/support checks','Direct visual review and corrections',
                    'Final renders, packaging and inspection registration']}
        shards=sorted((ref/'render_shards').glob('r*_*'))
        if candidates:
            revision=candidates[-1].stem.rsplit('_',1)[1]
            active=[p for p in shards if p.name.startswith(revision+'_')]
            progress=[]
            for shard in active:
                receipt=shard/'render_receipt.json'
                record=json.loads(receipt.read_text()) if receipt.exists() else {'frames':[]}
                progress.append({'shard':shard.name,'completed_frames':len(record['frames']),'views':[f['name'] for f in record['frames']]})
            status['current_render_progress']=progress
        if candidates:
            render_job=read('final_render_job_'+revision+'.json')
            if render_job:
                status['render_job']=render_job
                status['remaining']=['Finish all curated current-source renders','Direct reference/awkwardness review and any necessary fixes','Update gallery/inspection and deliver evidence to scene owner']
        delivered=read('delivery_visual_review_'+revision+'.json') if candidates else None
        ready=bool(delivered and delivered.get('ready_for_user_review') and delivered.get('session_visual_acceptance'))
        if ready:
            phase='session_reviewed_user_promotion_pending'
            status.update(phase=phase,visual_acceptance=True,user_approved=False,dataset_promoted=False,
                          delivery_review=delivered,remaining=['User review and optional dataset promotion'])
        (ref/'pipeline_status.json').write_text(json.dumps(status,indent=2))
        esc=lambda v:html.escape(str(v))
        def dump(obj):return '<pre>'+esc(json.dumps(obj,ensure_ascii=False,indent=2))+'</pre>'
        evidence=''
        for filename in ['floor_plan.json','room_mapping.json','scene_contract.json','preflight_layout.json']:
            if (ref/filename).exists():evidence+=f'<li><a href="{filename}">{filename}</a></li>'
        title='슬롯 2 · 사무실' if scene==SCENES[0] else '슬롯 3 · 2세대 주거층'
        document='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{font:16px/1.6 system-ui;background:#f3f5f8;color:#233047;margin:0}main{max-width:1180px;margin:auto;padding:24px}nav{display:flex;gap:8px;flex-wrap:wrap;position:sticky;top:0;background:#f3f5f8;padding:12px 0}button,a{color:#17618d}button{padding:10px 18px;cursor:pointer}section{background:white;padding:24px;border-radius:12px}section[hidden]{display:none}img{max-width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}h1{font-size:27px}.notice{background:#fff4d8;padding:14px;border-radius:8px}</style><main>'''
        document+='<p><a href="../scene_slots.html">세 슬롯 전체 현황</a></p>'
        notice='세션 전체 시각·물리 검수 완료 · 사용자 검토 대기 · 데이터셋 승격 없음' if ready else '진행 중 · '+phase+' · 최종 시각 검수 미완료'
        document+=f'<h1>{title}</h1><p>{esc(status["updated_at"])}</p><p class="notice">{esc(notice)}</p>' 
        if (ref/'realism_evaluation.json').exists():document+='<p class="notice"><a href="realism_progress.html">재질·메시 실사성 재평가와 Fine 라운드</a> · 기존 공간 검수와 별도 기준으로 보완 중</p>'
        document+='<nav role="tablist">'+''.join(f'<button role="tab" aria-selected="{str(i==0).lower()}" data-tab="{key}">{label}</button>' for i,(key,label) in enumerate([('current','현재 상태'),('plan','평면·레퍼런스'),('materials','재질 A/B'),('checks','검사·파이프라인'),('history','라운드 기록')]))+'</nav>'
        current_html=f'<p><b>최신 후보:</b> {esc(candidates[-1].name if candidates else "생성 전")} · {"사용자 검토 대기" if ready else "최종 합격 전"}</p><p>재질 변경은 ‘재질 A/B’, 방별 판정은 ‘라운드 기록’에서 확인할 수 있습니다.</p>'
        if (ref/'inspection_candidate.html').exists():current_html+='<p><a href="inspection_candidate.html">등록된 검수 후보 보기</a> · 등록된 전체 렌더 기준본이며, 최신 부분 수정은 아래 보고서에서 확인합니다.</p>'
        if render_receipts:
            latest=json.loads(render_receipts[-1].read_text())
            frame=next((f for f in latest['frames'] if f['name']=='overview'),latest['frames'][0] if latest['frames'] else None)
            if frame:
                relative=Path(frame['path']).relative_to(ref)
                current_html+=f'<figure><img src="{esc(relative)}" alt="최근 실제 렌더"><figcaption>최근 일반 렌더: {esc(render_receipts[-1].parent.name)} · {esc(frame["name"])} · 최신 후보의 전체 검수가 끝났다는 의미는 아닙니다.</figcaption></figure>'
        if delivered:current_html+='<p><b>직접 검수:</b> '+str(delivered['reviewed_frame_count'])+'개 뷰 · 미해결 주요 결함 '+str(len(delivered['major_unresolved_defects']))+'개</p><details><summary>현재 전체 검수 결과와 남은 차이</summary>'+dump(delivered)+'</details>'
        current_html+='<details><summary>세부 진행 상태·파일 근거</summary>'+dump(status)+'<ul>'+evidence+'</ul></details>'
        document+='<section id="current">'+current_html+'</section>'
        refs='';plan_review=read('plan_asset_review.json') or {}
        for image_path in ref.glob('*_reference_v*.png'):
            verdict=plan_review.get(image_path.name,{}).get('status','style_reference')
            figure=f'<figure><img loading="lazy" src="{esc(image_path.name)}" alt="{esc(image_path.stem)}"><figcaption>{esc(image_path.name)} · {esc(verdict)} · 스타일 기준, 배치 치수의 증거가 아닙니다.</figcaption></figure>'
            refs+=('<details><summary>기각된 생성 평면 · '+esc(image_path.name)+'</summary>'+figure+'</details>') if verdict.startswith('rejected') else figure
        plans=sorted((ref/'plan_renders').glob('r*/overview.png'),key=lambda p:int(p.parent.name[1:]))
        if render_receipts:
            latest_frames=json.loads(render_receipts[-1].read_text())['frames']
            native_overhead=next((f for f in latest_frames if f['name']=='overview'),None)
            if native_overhead:plans.append(Path(native_overhead['path']))
            plans=sorted(plans,key=lambda p:int(p.parent.name[1:]))
        if plans:
            refs='<h2>실제 씬의 고해상도 평면 렌더</h2><img loading="lazy" src="'+str(plans[-1].relative_to(ref))+'" alt="Actual scene overhead"><p>이미지 생성 평면의 방 개수 오류와 별도로 실제 씬에서 렌더한 배치입니다.</p>'+refs
        document+='<section id="plan" hidden><h2>사용자 제공 원본</h2><img src="source.png" alt="사용자 제공 원본"><p>배치는 원본을 기준으로 추정합니다. 생성 레퍼런스의 임의 변경을 건축 사실로 취급하지 않습니다.</p>'+refs+dump(read('plan_asset_review.json'))+dump(brief)+'</section>'
        detail_paths=sorted(ref.glob('material_detail_r*.json'),key=lambda p:int(p.stem.rsplit('r',1)[1]))
        detail=json.loads(detail_paths[-1].read_text()) if detail_paths else None;material_html='<p>재질별 추가 검수 기록을 준비 중입니다.</p>'
        if detail:
            material_html='<p>동일 카메라에서 비교합니다. 사무실 근접 비교는 비스듬한 진단 조명, 주거층 비교는 일반 실내 조명입니다. bump distance는 노드 설정값이며 실제 변위 측정값이 아닙니다.</p>'
            material_html+='<details><summary>재질 설정·형상 변경의 상세 근거</summary>'+dump({k:v for k,v in detail.items() if k not in ('changes','actual_object_assignments')})+'</details>'
            comparison=read('material_comparison.json') or {'views':[{'name':view,'baseline':f'material_renders/baseline_r9/{view}.png','candidate':f'material_renders/pbr_r10/{view}.png','label':'r10'} for view in ['carpet_detail','oak_worktop_detail','paint_detail','brushed_sink_detail','oak_floor_detail']]}
            ready=[i for i,row in enumerate(comparison['views']) if (ref/row['baseline']).exists() and (ref/row['candidate']).exists()]
            current_pair=max(ready) if ready else 0
            for pair_index,row in enumerate(comparison['views']):
                view=row['name']
                opened=' open' if pair_index==current_pair else ''
                material_html+=f'<details{opened}><summary>{esc(view)} · {esc(row["label"])}</summary><div style="display:flex;gap:12px;flex-wrap:wrap">'
                for path,label in [(row['baseline'],row.get('baseline_label','기존 r9')),(row['candidate'],'후보 '+row['label'])]:
                    image=ref/path
                    if image.exists():material_html+=f'<figure style="margin:0;flex:1;min-width:240px"><img loading="lazy" src="{esc(path)}" alt="{esc(view)} {esc(label)}"><figcaption>{esc(label)}</figcaption></figure>'
                    else:material_html+=f'<p>{esc(label)}: 렌더 대기</p>'
                material_html+='</div></details>'
            material_html+=dump(comparison.get('status','visual review pending'))
            reviews=sorted(ref.glob('material_visual_review*.json'),key=lambda p:p.stat().st_mtime)
            for reviewpath in reversed(reviews):
                material_html+=f'<details><summary>{reviewpath.name}</summary>'+dump(json.loads(reviewpath.read_text()))+'</details>'
        material_audits=sorted(list(ref.glob('material_audit_r*.json'))+list(ref.glob('materials_delivery_audit_r*.json')),key=lambda p:int(p.stem.rsplit('r',1)[1]))
        if material_audits:
            audit=json.loads(material_audits[-1].read_text())
            table='<table style="width:100%;font-size:13px"><tr><th>실제 적용 재질</th><th>종류</th><th>roughness 연결</th><th>normal 연결</th><th>metallic</th><th>적용 객체 수</th></tr>'
            for row in audit['records']:
                table+=f'<tr><td>{esc(row["material"])}</td><td>{esc(row["kind"])}</td><td>{row["linked_channels"]["Roughness"]}</td><td>{row["linked_channels"]["Normal"]}</td><td>{row["metallic"]}</td><td>{len(row["assigned_objects"])}</td></tr>'
            table+='</table>'
            material_html=f'<h3>실제 할당된 재질 채널 검사</h3><p>검사 파일: {esc(Path(audit["source"]).name)} · {audit["checked_assigned_materials"]}개 식별 재질 · 오류 {len(audit["errors"])}개. 노드 연결 검사는 시각적 사실성 합격과 별개입니다.</p><details><summary>채널 검사 표</summary>'+table+'</details><p><a href="'+material_audits[-1].name+'">전체 재질 채널 검사 근거</a></p>'+material_html
        document+='<section id="materials" hidden><h2>재질 근접 비교</h2>'+material_html+'</section>'
        audits=sorted(list(ref.glob('geometry_audit_r*.json'))+list(ref.glob('geometry_delivery_audit_r*.json')),key=lambda p:int(p.stem.rsplit('r',1)[1]))
        geometry=''
        if audits:
            current=json.loads(audits[-1].read_text())
            summary={k:current.get(k) for k in ['source','status','room_floors','furniture_count','errors','conservative_overlap_warnings','limitations']}
            summary['lighting_elevation_check_count']=len(current.get('lighting_elevation_checks',[]))
            summary['room_lighting_coverage_count']=len(current.get('room_lighting_coverage',[]))
            geometry=f'<h2>최근 실제 씬 검사</h2><a href="{audits[-1].name}">전체 검사 근거 JSON</a>'+dump(summary)
        for prefix,label in [('circulation_audit_r','실측 동선'),('stair_headroom_r','계단 머리 위 공간')]:
            paths=sorted(ref.glob(prefix+'*.json'),key=lambda p:int(p.stem.rsplit('r',1)[1]))
            if paths:
                audit=json.loads(paths[-1].read_text())
                geometry+=f'<h2>{label}</h2><a href="{paths[-1].name}">{paths[-1].name}</a>'+dump(audit)
        delivery_checks=sorted(ref.glob('delivery_audits_r*.json'),key=lambda p:int(p.stem.rsplit('r',1)[1]))
        if delivery_checks:
            dc=json.loads(delivery_checks[-1].read_text())
            geometry='<h2>현재 패킹본 검사</h2>'+dump(dc)+geometry
        native_checks=sorted(ref.glob('native_door_audit_r*.json'),key=lambda p:int(p.stem.rsplit('r',1)[1]))
        if native_checks:
            nd=json.loads(native_checks[-1].read_text())
            geometry+='<h2>실제 문짝·설비 메시 교차 검사</h2><a href="'+native_checks[-1].name+'">전체 검사 근거</a>'+dump({k:nd.get(k) for k in ['source','status','door_count','errors','limitations']})
        required_checks=sorted(ref.glob('required_spaces_audit_r*.json'),key=lambda p:int(p.stem.rsplit('r',1)[1]))
        if required_checks:
            rs=json.loads(required_checks[-1].read_text())
            geometry+='<h2>필수 공간·설비·카메라 대응</h2><a href="'+required_checks[-1].name+'">전체 대응표</a>'+dump({k:rs.get(k) for k in ['source','status','room_count','semantic_counts','actual_view_count','errors']})
        document+='<section id="checks" hidden><h2>렌더 전 사전검사</h2><p>공간 수·방 겹침·문 경계 부착·폭·전체 접근성 검사. 실제 가구 충돌과 지지 검사는 별도 단계입니다.</p>'+dump({'status':preflight['status'],'rooms':preflight['room_count'],'failures':preflight['failures']} if preflight else {'status':'pending'})+geometry+'</section>'
        history=''
        for round_index,receiptpath in enumerate(reversed(render_receipts)):
            receipt=json.loads(receiptpath.read_text());revision=receiptpath.parent.name
            opened=' open' if round_index==0 else ''
            history+=f'<details{opened}><summary>{esc(revision)} · {len(receipt["frames"])}개 실제 렌더</summary>'
            review=read(f'delivery_visual_review_{revision}.json') or read(f'visual_review_{revision}.json')
            history+=dump(review or {'status':'direct_visual_review_pending'})
            for frame in receipt['frames']:
                image=Path(frame['path']);relative=image.relative_to(ref)
                history+=f'<figure><img loading="lazy" src="{esc(relative)}" alt="{esc(frame["name"])}"><figcaption>{esc(frame["name"])} · {frame["width"]}×{frame["height"]}</figcaption></figure>'
            history+='</details>'
        document+='<section id="history" hidden><h2>제작·검수 기록</h2>'+history+dump(state or {'status':'not_started'})+'</section>'
        document+='''</main><script>for(const b of document.querySelectorAll('[data-tab]'))b.onclick=()=>{for(const s of document.querySelectorAll('section'))s.hidden=s.id!==b.dataset.tab;for(const t of document.querySelectorAll('[data-tab]'))t.setAttribute('aria-selected',String(t===b));location.hash=b.dataset.tab};const start=document.querySelector('[data-tab="'+location.hash.slice(1)+'"]');if(start)start.click();</script></html>'''
        path=ref/'progress.html'
        backup=ref/'progress_before_pipeline.html'
        if path.exists() and not backup.exists():backup.write_bytes(path.read_bytes())
        temp=path.with_suffix('.html.tmp');temp.write_text(document);temp.replace(path)
        print(path)


if __name__=='__main__':main()
