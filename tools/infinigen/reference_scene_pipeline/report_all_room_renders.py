"""Compact two-scene gallery, bound to completed full-source render receipts.

Uses external JPEG previews/full views so large PNGs never block the report UI.
"""
import datetime
import hashlib
import html
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
B = ROOT / 'data/venue_refs/floor_plans_v3'
D = B / 'all_room_renders'
E = lambda value: html.escape(str(value), quote=True)


def main():
    D.mkdir(exist_ok=True)
    images = D / 'images'; images.mkdir(exist_ok=True)
    sections, evidence = [], []
    total_views = 0
    labels = {'overview':'전체 평면', 'breakout_kitchen':'탕비실',
              'reception':'리셉션', 'conference_a':'회의실 A',
              'meeting_b':'회의실 B', 'meeting_c':'회의실 C',
              'private_office':'개인 사무실1', 'support_west':'서측 지원공간',
              'support_east':'동측 지원공간', 'stairs':'계단',
              'elevator_context':'승강기', 'shared_corridor_context':'공용 복도'}
    for key, scene, revision, expected, title in [
        ('office','commercial_office_floor_02',102,16,'사무실 전체 · r102'),
        ('home','dual_unit_residential_floor_03',103,39,'주거층 전체 · r103')]:
        receipt_path = B/scene/f'full_suite_r{revision}/candidate/render_receipt.json'
        receipt = json.loads(receipt_path.read_text())
        assert len(receipt['frames']) == expected
        assert len({f['name'] for f in receipt['frames']}) == expected
        source = Path(receipt['source'])
        assert hashlib.sha256(source.read_bytes()).hexdigest() == receipt['source_sha256']
        frames = list(receipt['frames'])
        pending = ''
        if key == 'office':
            supplement = B/scene/'all_private_offices_r102/candidate/render_receipt.json'
            if supplement.exists():
                extra = json.loads(supplement.read_text())
                assert extra['source_sha256'] == receipt['source_sha256']
                assert {f['name'] for f in extra['frames']} == {f'private_office_{i}' for i in range(2,7)}
                assert extra['renderer_sha256'] == receipt['renderer_sha256']
                frames += extra['frames']
            else:
                pending = ' 개인 사무실2–6 개별 시점5개는 추가 렌더 중입니다. 현재16뷰를 모든 개별 방의 완전한 커버리지로 보지 않습니다.'
        ordered = sorted(frames, key=lambda f: (f['name'] != 'overview', f['name']))
        total_views += len(ordered)
        cards = []
        for frame in ordered:
            src = Path(frame['path'])
            assert hashlib.sha256(src.read_bytes()).hexdigest() == frame['sha256']
            stem = f'{key}_{revision}_{frame["name"]}'
            thumb, large = images/f'{stem}_thumb.jpg', images/f'{stem}.jpg'
            for out, size, quality in [(thumb,(640,480),76),(large,(1600,1200),88)]:
                if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
                    with Image.open(src) as image:
                        image = image.convert('RGB'); image.thumbnail(size)
                        image.save(out, quality=quality, optimize=True)
            name = frame['name']; group = '101' if name.startswith('101_') else '102' if name.startswith('102_') else '공용·상세'
            label = labels.get(name,name.replace('_',' '))
            cards.append(f'<article data-search="{E(name+" "+label+" "+group)}"><a class="view" href="images/{E(large.name)}" data-caption="{E(title+" / "+label)}"><img loading="lazy" src="images/{E(thumb.name)}" alt="{E(label)}"></a><h3>{E(label)}</h3><p>{E(name)} · {frame["width"]}×{frame["height"]} · {frame["samples"]}spp</p><a href="images/{E(large.name)}" target="_blank">JPEG 크게 열기</a></article>')
        review = f'../{scene}/full_suite_r{revision}/' + ('review.html' if key=='home' else 'visual_review.json')
        note = ('최신 전체 렌더는 r102입니다. 이후 r105 목재·r107 테이블은 국소 비교만 끝났으며, r107은 보류입니다.' if key=='office' else
                'r103 필수39뷰 렌더·독립검수 완료. 변기 접근성은 국소 개선됐지만 전체 실사성은 불합격입니다. 코어WC104는 배치 수정 초안이며 이 갤러리에 섞지 않았습니다.')
        sections.append(f'<section id="{key}"'+(' hidden' if key!='office' else '')+f'><h2>{E(title)} · {len(ordered)}뷰</h2><p class="notice">{E(note+pending)}</p><p><a href="{review}">전체 비평 근거</a> · <a href="../{scene}/fine_current.html">라운드별 비교 보고서</a></p><input aria-label="방 이름 검색" placeholder="방 검색: 101, 102, bedroom, bathroom, meeting…"><div class="grid">'+''.join(cards)+'</div></section>')
        evidence.append({'scene':scene,'revision':revision,'views':len(ordered),'receipt':str(receipt_path),'source':str(source),'source_sha256':receipt['source_sha256'],'all_frame_hashes_verified':True,'photorealism_accepted':False,'supplementary_private_room_views_pending':bool(pending)})
    css='body{font:16px/1.6 system-ui;margin:0;background:#f4f5f7;color:#20252c}main{max-width:1450px;margin:auto;padding:24px}nav{display:flex;gap:10px;position:sticky;top:0;padding:12px;background:#f4f5f7;z-index:2}button,input{font:inherit;padding:10px 15px}button{cursor:pointer}button[aria-selected=true]{background:#243b50;color:white}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:18px}article{background:white;border-radius:10px;padding:12px}article img{width:100%;height:auto;aspect-ratio:4/3;object-fit:contain}h3{margin:8px 0}article p{font-size:13px;color:#59616c;overflow-wrap:anywhere}.notice{border-left:4px solid #be8b2b;padding:12px;background:#fff7e5}section[hidden],article[hidden]{display:none}input{width:min(90%,700px);margin:12px 0}dialog{max-width:95vw;max-height:95vh;padding:12px;border:0;border-radius:10px}dialog img{display:block;max-width:90vw;max-height:80vh}dialog::backdrop{background:#000b}dialog button{float:right}'
    script='''const tabs=document.querySelectorAll('[data-tab]');function tab(id){for(const s of document.querySelectorAll('section'))s.hidden=s.id!==id;for(const b of tabs)b.setAttribute('aria-selected',b.dataset.tab===id);location.hash=id;}for(const b of tabs)b.onclick=()=>tab(b.dataset.tab);tab(location.hash==='#home'?'home':'office');for(const input of document.querySelectorAll('input'))input.oninput=()=>{for(const c of input.closest('section').querySelectorAll('article'))c.hidden=!c.dataset.search.toLowerCase().includes(input.value.toLowerCase());};const dialog=document.querySelector('dialog');for(const a of document.querySelectorAll('a.view'))a.onclick=e=>{if(!dialog.showModal)return;e.preventDefault();dialog.querySelector('img').src=a.href;dialog.querySelector('p').textContent=a.dataset.caption;dialog.showModal();};dialog.querySelector('button').onclick=()=>dialog.close();dialog.onclick=e=>{if(e.target===dialog)dialog.close();};'''
    office_views = evidence[0]['views']
    page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>두 씬 모든 방 렌더</title><style>'+css+'</style><main><a href="../scene_slots.html">씬 슬롯 현황</a><h1>모든 방 렌더 · 사무실 / 주거층</h1><p>전체'+str(total_views)+'뷰 · 생성 '+datetime.datetime.now(datetime.timezone.utc).isoformat()+' · 방 이미지를 누르면 확대됩니다. 각 탭은 동일 소스의 렌더 묶음입니다.</p><p>현재 두 씬 모두 최종 실사성 불합격이며 사용자 승인·데이터셋 승격은 없습니다.</p><nav><button data-tab="office">사무실 · '+str(office_views)+'뷰</button><button data-tab="home">주거층 · 39뷰</button></nav>'+''.join(sections)+'<p><a href="evidence.json">소스·이미지 해시 검증 근거</a></p></main><dialog><button>닫기</button><p></p><img alt="렌더 확대"></dialog><script>'+script+'</script></html>'
    assert len(page.encode()) < 60000
    (D/'report.html').write_text(page)
    (D/'evidence.json').write_text(json.dumps({'scenes':evidence,'total_views':total_views,'no_drafts_mixed':True},indent=2)+'\n')
    print('ALL_ROOM_REPORT',D/'report.html',len(page.encode()),f'bytes;{total_views} source-bound frames verified')


if __name__ == '__main__':
    main()
