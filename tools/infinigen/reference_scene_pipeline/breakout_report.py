"""Compact tabs for the controlled breakout realism investigation."""
import json,html
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';out=ref/'breakout_diagnostics_r28';job=json.loads((out/'job.json').read_text());esc=lambda x:html.escape(str(x));page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>탕비실 실사성 원인 분리</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:24px auto;padding:16px}nav{display:flex;gap:12px;flex-wrap:wrap}button{padding:10px}section[hidden]{display:none}img{max-width:100%}section{padding:20px;background:#f1f4f7;margin-top:20px}</style><a href="../realism_progress.html">실사성 보고서</a><h1>탕비실 · 원인 분리 실험 r28</h1><p>현재 상태: '+esc(job['phase'])+' · CPU · 동일 카메라/1024px/48spp/AgX 노출0. 최종 실사성 합격 전.</p><p>사용자 평가 5.8/10은 제공된 축소 렌더에 대한 주관적 평가이며, 보정 후 자동 측정 점수로 사용하지 않습니다.</p><nav>'
labels={'A':'A 기준','B':'B 측면광만','C':'C1 재질 반응','C2':'C2 다른 목재 스캔','G':'G 형상만'}
for key,label in labels.items():page+='<button data-tab="'+key+'">'+label+'</button>'
page+='</nav>'
review=out/'visual_review.json'
if review.exists():
 d=json.loads(review.read_text());page+='<p>실사성 최종 합격 전. 판단 기록:</p><ul>'+''.join('<li><b>'+esc(k)+'</b>: '+esc(v)+'</li>' for k,v in d['decisions'].items())+'</ul>'
for key,label in labels.items():
 page+='<section id="'+key+'"'+(' hidden' if key!='A' else '')+'><h2>'+label+'</h2><p>'+esc(job['variants'][key])+'</p>'
 p=out/key/'breakout_kitchen.png'
 if p.exists():
  target=out/(key+'_preview.jpg')
  with Image.open(p) as im:im.convert('RGB').save(target,quality=87,optimize=True)
  page+='<a href="'+key+'/breakout_kitchen.png"><img src="'+target.name+'" loading="lazy"></a>'
 else:page+='<p>렌더 대기. 아직 개선 판단을 내리지 않았습니다.</p>'
 page+='</section>'
page+='<p>판단 기준: 형광등 외곽·접촉 그림자·재질별 하이라이트·의자 실루엣·캐비닛 틈. 밝기나 거칠기 증가 자체를 성공으로 인정하지 않습니다. B는 진단용 소프트박스로 최종 설치 조명이 아닙니다. C의 대체 스캔 역시 렌더로 평가해야 합니다.</p><script>for(const b of document.querySelectorAll("button"))b.onclick=()=>{for(const s of document.querySelectorAll("section"))s.hidden=s.id!==b.dataset.tab}</script>'
(out/'report.html').write_text(page);print(out/'report.html')
p=ref/'realism_evaluation.json';d=json.loads(p.read_text());d['breakout_diagnostic_report']='breakout_diagnostics_r28/report.html';d['breakout_diagnostic_status']=job['phase'];p.write_text(json.dumps(d,ensure_ascii=False,indent=2))
