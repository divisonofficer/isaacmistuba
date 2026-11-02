"""Compact paged material-lobe inventory, separate from photographic acceptance."""
import argparse,json,html,math
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--inventory',required=True,type=Path);a=p.parse_args()
d=json.loads(a.inventory.read_text());folder=a.inventory.parent;stem=a.inventory.stem
esc=lambda value:html.escape(str(value))
style='body{font:15px/1.6 system-ui;max-width:1250px;margin:auto;padding:22px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px;text-align:left;overflow-wrap:anywhere}nav{display:flex;gap:12px;flex-wrap:wrap}.scroll{overflow-x:auto}small{color:#555}'
def shell(title,body):return '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>'+esc(title)+'</title><style>'+style+'</style><a href="fine_current.html">씬 검수 보고서</a><h1>'+esc(title)+'</h1>'+body+'</html>'
rows=d['materials'];pages=max(1,math.ceil(len(rows)/30));links=' · '.join('<a href="'+stem+f'_page_{i+1:02}.html">{i+1}</a>' for i in range(pages))
def value(material,name):
    values=[]
    for node in material['reachable_principled']:
        item=node['inputs'][name];values.append('연결됨' if item['constant'] is None else f"{item['constant']:.3f}")
    return ' / '.join(values) if values else 'Principled 외 셰이더'
for i in range(pages):
    body='<nav><a href="'+stem+'_review.html">범위·요약</a>'+links+'</nav><p>수치는 연결되지 않은 상수 입력값입니다. 연결 맵과 혼합 가중치는 평가하지 않습니다.</p><div class="scroll"><table><thead><tr><th>재질</th><th>객체 수·예</th><th>직물 후보</th><th>Coat</th><th>Roughness</th><th>Sheen</th></tr></thead><tbody>'
    for row in rows[i*30:(i+1)*30]:
        names=row['bound_objects'];objects=str(len(names))+'개 · '+'; '.join(names[:3])
        if len(names)>3:objects+=' …'
        hint='검토 표시' if row['positive_constant_coat_on_hinted_textile_review'] else ('이름·태그상 후보' if row['textile_hint_provisional'] else '분류 미확정')
        body+='<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [row['material'],objects,hint,value(row,'Coat Weight'),value(row,'Roughness'),value(row,'Sheen Weight')])+'</tr>'
    page=shell('재질 반사 성분 목록 · '+str(i+1),body+'</tbody></table></div>');assert len(page.encode())<100000
    (folder/(stem+f'_page_{i+1:02}.html')).write_text(page)
    
body='<p>소스: '+esc(d['source'])+'</p><p>SHA256: <code>'+esc(d['source_sha256'])+'</code></p><p>렌더 허용 객체의 할당된 노드 재질 '+str(len(rows))+'개. 이름·태그상 직물 후보의 상수 Coat 검토 표시 '+str(d['hinted_textile_review_flags'])+'개.</p><p>이 표시는 오류/합격 판정이 아닙니다. 원본의 객체 hide_render와 활성 Surface 연결만 조사했으며, 컬렉션·광선 가시성, 연결 맵의 유효 값, 중첩 그룹과 혼합 가중치는 해석하지 않았습니다. 직물 분류도 이름/태그의 잠정 추정입니다. 실제 사진 사실성은 비교 렌더에서 검수합니다.</p><nav>'+links+'</nav><p><a download href="'+esc(a.inventory.name)+'">전체 원시 JSON 다운로드</a></p>'
out=folder/(stem+'_review.html');out.write_text(shell('재질 반사 성분 · 범위와 목록',body));print(out.resolve())
