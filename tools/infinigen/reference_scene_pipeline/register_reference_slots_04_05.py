"""Register user-requested references; never claims generated scene or approval."""
import copy
import datetime
import hashlib
import html
import json
import shutil
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
B = ROOT/'data/venue_refs/floor_plans_v3'


def main():
    specs = [
        {'slot':4, 'scene_id':'rural_stone_cottage_04', 'type':'rural_stone_cottage',
         'title':'농촌 석조 주택', 'seed':48712504,
         'source':'/tmp/orca-paste-1793084387724-8011b6f8-2532-4635-9272-94df088ed760.png',
         'spaces':['거실·주방','안방','작업실·서재','보조 주방','좌측 창고','상단 창고','현관·마루','외부 정원·석재 진입로'],
         'requirements':['불규칙 석조 벽체와 모르타르 줄눈의 실제 깊이·모서리·기하 변화',
                         '노출 목재 보·서까래·지붕 접합, 부재별 결 방향과 자연스러운 변형',
                         '중첩된 개별 석재 지붕 슬레이트와 처마의 두께·그림자',
                         '상세 제품 가구·주방 도구·장작·항아리·바구니·책·직물',
                         '벽난로·굴뚝의 연결과 사용 공간, 눈높이에서 읽히는 실내외 깊이',
                         '흙·자갈·석재 포장·관목·나무의 지면 접촉과 식생 계층'],
         'uncertainties':['치수가 없는 이미지이므로 초기 SI 치수는 추정치이며 제품 실측 크기로 보정해야 함',
                          '우측 지붕 아래 일부 공간은 가려져 있으며 기능·문 위치를 확정할 수 없음',
                          '욕실이 제시되지 않았으므로 임의로 추가하지 않고 가려진 영역과 구분']},
        {'slot':5, 'scene_id':'shared_dining_residence_05', 'type':'shared_dining_residence',
         'title':'공동 식사 공간 주거', 'seed':48712505,
         'source':'/tmp/orca-paste-1793084496135-5acc5676-ef78-41d4-a7e8-b24b85802573.png',
         'spaces':['트윈 침실','주 주방','직사각 대형 식탁','중앙 소형 원형 식탁','하단 대형 원형 식탁','벽면 소파·음식 진열대','타일 마감 보조 주방·가사 공간','세탁·개수 설비','소형 화장실','출입·연결 동선'],
         'requirements':['트윈 침대 두 개의 실제 크기·서로 다른 침구 주름·눌림·봉제',
                         '세 식탁의 크기·좌석 수와 개별 배치, 상세 제품 의자·라탄·직물',
                         '실제 제품 식기·음식·음료·식물로 레퍼런스 식탁 밀도 재현',
                         '목재 바닥/가구·회색 타일·도장 벽·세라믹·금속의 서로 다른 반사',
                         '보조 주방·세탁기·개수대·냉장고의 실제 조립·배관·지지',
                         '소형 화장실은 성인 native 변기 크기와 문 열림·600mm 동선부터 검증',
                         '큰 평면 뷰뿐 아니라 모든 기능 공간의 사람 눈높이 렌더 검수'],
         'uncertainties':['측량 치수가 없는 이미지이며 초기 SI 크기는 추정',
                          '좌측 회색 타일 공간의 실내외 여부가 명확하지 않아 중정으로 단정하지 않음',
                          '도면에 없는 샤워실이나 추가 침실을 임의로 생성하지 않음']},
        {'slot':6, 'scene_id':'industrial_workshop_floor_06', 'type':'industrial_workshop',
         'title':'기계 작업장·정비 공장층', 'seed':48712506,
         'source':'/tmp/orca-paste-1793084698005-c3c266ce-4180-4e44-9d17-b67f82b3dcb5.png',
         'spaces':['상부 대형 작업장','좌측 독립 정비실','하단 중앙 장비·부품실','우측 독립 정비실','중앙 출입·계단실','작업대·공구 수납','설비 배관·외벽 창'],
         'requirements':['실제 상세 기계·엔진·공구·작업대·보관함 제품으로 큰 형상부터 구성',
                         '콘크리트 기둥·바닥·벽의 시공 이음, 표면 스케일 차이와 실제 모서리',
                         '상부 노출 배관의 조인트·지지 클램프·벽 접촉, 전원·작업등 연결',
                         '사용 중인 작업대별 서로 다른 정비 작업 구성과 지지·안전한 통로',
                         '도장 금속·노출 강재·고무·기름 자국·석재/콘크리트의 구별',
                         '창의 자연광과 국소 작업등, 실제 외부 배경과 강약 있는 반사',
                         '모든 독립 실과 연결 동선의 눈높이 렌더·물리 회귀 검수'],
         'uncertainties':['기계의 구체 모델·산업 용도는 단일 이미지로 확정하지 않음',
                          '치수·층고·바깥층 연결은 추정이므로 제품 크기와 계단 동선으로 보정',
                          '창과 출입문 위치는 이미지 기준이며 도면 없는 추가 실을 발명하지 않음']},
        {'slot':7, 'scene_id':'large_restaurant_floor_07', 'type':'large_restaurant',
         'title':'대형 식당', 'seed':48712507,
         'source':'/tmp/orca-paste-1793084850512-ff36875b-bb5a-4f82-b32f-6701789b3bbd.png',
         'spaces':['주 주방·식재 준비·개수·냉장 설비','L자 서비스 바·카운터 좌석','중앙 일반 식사 홀','상단 개별 식사실1','상단 개별 식사실2','상단 개별 식사실3','상단 개별 식사실4','하단 단체용 대형 식탁','좌측 소파 대기·식사 구역','좌하단 개별 식사실','계산·접객 카운터','우상단 화장실','우하단 화장실','좌하단 소형 화장실','출입·서비스 연결 통로'],
         'requirements':['좌석 수·식탁 크기·배치를 레퍼런스에 맞추고 손님·서비스 통로를 실제 형상으로 검증',
                         '실제 고상세 테이블·라탄/목재 의자·스툴·소파·식기·음식 제품 사용',
                         '화구·싱크·개수·냉장고·작업대의 실제 장비 크기와 제조 조립',
                         '적갈색 바닥·짙은 목재·밝은 석재 상판·청록 좌석의 고유 반사·미세 요철',
                         '식물은 중앙 화분·벽면·대기 구역별 종류·크기·밀도를 구분',
                         '화장실은 각 stall 문 열림·성인 native 변기·접근로부터 검증',
                         '모든 독립 방과 홀·서비스 바의 눈높이/근접 및 전체 평면 렌더'],
         'uncertainties':['도면 치수·층고와 정확한 영업 좌석 수는 이미지 기반 추정',
                          '화장실 용도 구분·벽 내부 설비·후방 외부 연결은 임의 단정하지 않음',
                          '조감도에서 가려진 장비나 벽면은 확인된 레퍼런스와 구분해 표시']},
        {'slot':8, 'scene_id':'skyline_penthouse_08', 'type':'penthouse_residential',
         'title':'도시 전망 펜트하우스', 'seed':48712508,
         'source':'/tmp/orca-paste-1793084922078-e3e3c346-d868-4a93-a824-19abb4b0c348.png',
         'spaces':['거실','식당','주 주방·대형 아일랜드','보조 주방·세탁실','서재','현관·홀','게스트 화장실','마스터 침실','마스터 드레스룸','마스터 욕실','패밀리룸','침실2','침실2 욕실','침실3','침실3 욕실','외곽 테라스·야외 식사·정원'],
         'requirements':['천장까지 이어지는 통유리와 검은 프레임, 도시의 깊이·수목·테라스 난간',
                         '부드러운 모듈 소파·곡선 소파·침구의 충전량·접촉·봉제와 미세 직물',
                         '대형 석재 상판·타일의 실측 스케일·맥 흐름·줄눈·모서리 및 반사 차이',
                         '서재 책·실제 데스크 제품과 개별 수납, walk-in 드레스룸의 실제 의류',
                         '세 침실·네 욕실 역할을 독립 검증하고 native 성인 변기/문/접근 여유 유지',
                         '간접 코브·펜던트·다운라이트·스탠드의 실제 등기구 구조와 조명 계층',
                         '마스터 욕조·샤워·세면대·주방 장비의 실제 제품 형상과 제조·접합 디테일',
                         '모든 방과 테라스의 레퍼런스 대응 눈높이 렌더·재질 근접 검수'],
         'uncertainties':['도면의 일부 한글 방 표기가 겹치거나 불일치하므로 시각적 기능과 방 수를 우선 확인',
                          '실측 치수·도시 위치·층고는 제공되지 않아 초기 값은 추정치로 표시',
                          '테라스 높이·배수·외벽 구조는 실제 배치와 제품에 맞춰 검증 필요']},
        {'slot':9, 'scene_id':'double_height_duplex_09', 'type':'duplex_apartment',
         'title':'복층 아파트', 'seed':48712509,
         'source':'/tmp/orca-paste-1793085160554-3f7742df-b826-498c-b04a-3ca4f9ca2122.png',
         'spaces':['1F 거실·높은 천장','1F 주방·아일랜드','1F 다이닝','1F 서재·작업실','1F 화장실·보조 설비','1F 현관·라운지','1F 테라스','층간 계단·실내 정원','중앙 보이드·상층 갤러리','2F 마스터 침실','2F 마스터 욕실','2F 드레스룸','2F 침실2','2F 침실3','2F 공용 욕실','2F 테라스·외부 욕조'],
         'requirements':['두 층의 실제 Z 높이·슬래브·중앙 보이드를 별도 저작; 평면 두 장을 같은 높이에 두지 않음',
                         '계단의 일관된 단높이/디딤판·실제 지지·난간과 층간 접근 그래프',
                         '상층 보이드 가장자리 유리 난간의 두께·고정 브래킷·연결',
                         '복층 높이 통유리·커튼·실제 도시 배경과 층별 일관된 전망',
                         '실내 정원·계단벽 석재·실제 펜던트와 코브 조명의 재질별 빛 반응',
                         '두 층 모든 방의 native 상세 가구·침구·의류·주방/욕실 제품',
                         '각 층 독립 평면·계단 양방향·보이드 위아래·모든 방 눈높이 렌더',
                         '문·성인 변기·동선·지지·상하층 충돌과 수직 시야/렌더 회귀 검사'],
         'uncertainties':['층별 일부 작은 실의 기능·치수는 이미지로 확정되지 않음',
                          '층고와 구조 두께는 측량 값이 없으므로 초기 가정으로 기록하고 계단/문 크기로 보정',
                          '원본 내부 사진과 조감도 사이 세부 배치는 시각적 차이를 기록하며 조정']}
    ]
    path = B/'scene_slots.json'
    slots = json.loads(path.read_text())
    previous = copy.deepcopy(slots['slots'])
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for spec in specs:
        scene = spec['scene_id']; d = B/scene; d.mkdir(exist_ok=True)
        src, dest = Path(spec['source']), d/'source.png'
        if dest.exists():
            assert hashlib.sha256(dest.read_bytes()).digest() == hashlib.sha256(src.read_bytes()).digest()
        else:
            shutil.copyfile(src,dest)
        with Image.open(dest) as im:
            im = im.convert('RGB'); im.thumbnail((1400,1000)); im.save(d/'reference_preview.jpg',quality=88,optimize=True)
        contract = {**spec,'stage':'reference_registered_not_rendered','reference_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),
                    'source_image':'source.png','native_high_detail_assets_required':True,
                    'no_box_or_primitive_product_standins':True,
                    'review_rules':['동일 카메라·샘플·노출 A/B',
                                    '각 방 렌더·눈높이와 필요한 근접 고해상도 검사',
                                    '기하 audit 통과와 사진 사실성·레퍼런스 유사도를 분리',
                                    '높은 심각도 독립 검수 결함 해결 전 완료 금지'],
                    'gpu_policy':'CPU until explicit current SONNET_GPU_MANAGER allocation',
                    'candidate_blend':None,'render_count':0,'user_approved':False,
                    'photorealism_accepted':False,'dataset_promoted':False}
        (d/'scene_request.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n')
        esc=lambda x:html.escape(str(x))
        tabs={'reference':('레퍼런스','<p>사용자 제공 이미지입니다. 생성한3D 렌더가 아닙니다.</p><a href="source.png"><img src="reference_preview.jpg"></a>'),
              'spaces':('공간·품질 기준','<h2>필수 공간</h2><ul>'+''.join('<li>'+esc(t)+'</li>' for t in spec['spaces'])+'</ul><h2>제작·검수 기준</h2><ul>'+''.join('<li>'+esc(t)+'</li>' for t in spec['requirements'])+'</ul>'),
              'status':('현황·불확실성','<p>레퍼런스 등록 완료. 아직 Blender 후보·렌더 없음. 데이터셋 승격 없음.</p><ul>'+''.join('<li>'+esc(t)+'</li>' for t in spec['uncertainties'])+'</ul><a href="scene_request.json">전체 요청·소스 해시</a>')}
        page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+esc(spec['title'])+'</title><style>body{font:16px/1.65 system-ui;max-width:1150px;margin:auto;padding:24px}img{max-width:100%;height:auto}button{padding:12px;margin-right:10px}section[hidden]{display:none}section{margin-top:20px}li{margin:10px 0}</style><a href="../scene_slots.html#slot'+str(spec['slot'])+'">전체 슬롯</a><h1>슬롯 '+str(spec['slot'])+' · '+esc(spec['title'])+'</h1><p>레퍼런스 등록 · 3D 생성 전</p><nav>'+''.join('<button data-tab="'+k+'">'+v[0]+'</button>' for k,v in tabs.items())+'</nav>'+''.join('<section id="'+k+'"'+(' hidden' if k!='reference' else '')+'>'+v[1]+'</section>' for k,v in tabs.items())+'<script>for(const b of document.querySelectorAll("[data-tab]"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab;};</script></html>'
        (d/'progress.html').write_text(page)
        (d/'current_visual_status.json').write_text(json.dumps({'updated_at':timestamp,'stage':'reference_registered','render_count':0,'current_full_scene_review_complete':False,'photorealism_accepted':False,'dataset_promoted':False},indent=2)+'\n')
        existing = next((r for r in slots['slots'] if r['slot']==spec['slot']),None)
        if existing:
            assert existing['scene_id']==scene
            continue
        slots['slots'].append({'slot':spec['slot'],'scene_id':scene,'type':spec['type'],
                               'title':spec['title'],'seed':spec['seed'],'status':'reference_registered',
                               'reference_root':str(d),'revision':'reference_only','blend':'',
                               'render_count':0,'overview':str(d/'reference_preview.jpg'),'overview_kind':'reference',
                               'report':str(d/'progress.html'),'inspection':str(d/'progress.html'),
                               'visual_acceptance':False,'user_approved':False,'photorealism_accepted':False,
                               'dataset_promoted':False,'updated_at':timestamp})
    assert slots['slots'][:len(previous)] == previous, 'Preserve all existing slot records'
    slots['updated_at'] = timestamp
    path.write_text(json.dumps(slots,ensure_ascii=False,indent=2)+'\n')
    print('Registered slots4 through9; previous slots unchanged; no scene/render/promotion claimed.')


if __name__ == '__main__':
    main()
