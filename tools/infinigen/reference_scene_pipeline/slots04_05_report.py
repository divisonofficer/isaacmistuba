"""Owned two-scene progress pages: links only to extant exact-source evidence."""
import html,json,os
from pathlib import Path
from PIL import Image
R=Path(__file__).resolve().parents[3]
def read(p):
 try:return json.loads(p.read_text())
 except (OSError,json.JSONDecodeError):return {}
def atomic(p,text):
 t=p.with_name(p.name+f'.{os.getpid()}.tmp');t.write_text(text);t.replace(p)
def live(pid,source):
 try:
  command=Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode();stat=Path(f'/proc/{pid}/stat').read_text();return {'pid':pid,'alive':stat.split(') ',1)[1][0]!='Z','matches_source':source in command,'command':command}
 except (OSError,ValueError):return {'pid':pid,'alive':False,'matches_source':False}
for scene,seed,slot in [('rural_stone_cottage_04',48712504,'04'),('shared_dining_residence_05',48712505,'05')]:
 d=R/'data/venue_refs/floor_plans_v3'/scene;w=R/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';candidate=next((w/(f'scene_candidate_slots{slot}_r6_metric.blend' if i==6 else f'scene_candidate_slots{slot}_r{i}.blend') for i in [6,5,4,3,2,1] if (w/(f'scene_candidate_slots{slot}_r6_metric.blend' if i==6 else f'scene_candidate_slots{slot}_r{i}.blend')).exists()),w/'scene.blend');jobs=[];evidence=[]
 for rev in [1,2,3,4,5,6]:
  parent=d/('candidate_r6_metric_cpu' if rev==6 else f'candidate_r{rev}_cpu');job=read(parent/'job.json');receipt=read(parent/'render/render_receipt.json');frames=sorted((parent/'render').glob('*.png'))
  if job:
   source=job.get('source','');jobrow={'revision':rev,'source':source,'job_path':str(parent/'job.json'),'phase':job.get('phase'),'exit_code':job.get('exit_code'),'actual_process':live(job.get('child_pid',-1),source)};jobs.append(jobrow)
  # A PNG needs an actual renderer receipt before it is presented as exact-source evidence.
  if frames and receipt.get('source'):
   evidence.append({'revision':rev,'source':receipt['source'],'sha256':receipt.get('source_sha256'),'frames':frames,'receipt_path':parent/'render/render_receipt.json','job_path':parent/'job.json'})
 current=evidence[-1] if evidence else {};frames=current.get('frames',[]);previews=[]
 for f in frames:
  out=d/f"candidate_r{current['revision']}_{f.stem}_preview.jpg"
  if not out.exists() or out.stat().st_mtime<f.stat().st_mtime:
   with Image.open(f) as im:
    im=im.convert('RGB');im.thumbnail((960,720));im.save(out,quality=88)
  previews.append((out.name,f.relative_to(d).as_posix()))
 review=read(d/('candidate_r6_metric_visual_review.json' if '_r6_metric' in candidate.name else 'candidate_r5_visual_review.json'));latest_reviewed=review.get('source_candidate')==str(candidate) and bool(review.get('directly_inspected_frames'));live_jobs=[j for j in jobs if j['actual_process']['alive'] and j['actual_process']['matches_source']]
 status=('corrected_render_suite_reviewed_major_issues_open' if review.get('review_complete') else 'corrected_candidate_partially_reviewed_major_issues_open') if latest_reviewed else ('newer_saved_candidate_unreviewed_existing_views_available' if current and current['source']!=str(candidate) else 'rendered_visual_review_pending' if frames else 'saved_candidate_render_pending')
 issues=(['Rustic masonry courses, slate roof, garden and detailed timber joinery absent','Native modern kitchens and catalog furniture differ substantially from rural source','Source bedding/decoration density absent; exact saved-mesh collisions, doors and service connections remain unaudited'] if slot=='04' else ['Single native bed frames lack reference mattresses and bedding','Repeated CH71 lounge chairs have inappropriate dining seat height and style','Food, display, wall sofa, rugs and planting density absent','Utility floor differs from reference gray square tiles; services need saved-view and clearance review'])
 if latest_reviewed:issues=review.get('findings',issues)
 overview=next((f for f in frames if f.name.startswith('overview')),None)
 data={'scene_id':scene,'status':status,'latest_candidate_blend':str(candidate),'latest_candidate_visually_reviewed':latest_reviewed,'latest_candidate_review_scope_complete':bool(latest_reviewed and review.get('review_complete')),'latest_candidate_review_scope':review.get('review_scope'),'overview':str(overview) if overview else None,'render_count':sum(len(e['frames']) for e in evidence),'displayed_render_count':len(frames),'displayed_render_source':current.get('source'),'displayed_render_source_sha256':current.get('sha256'),'report':str(d/'progress.html'),'open_items':issues,'render_jobs':jobs,'actual_live_render_count':len(live_jobs),'photorealism_accepted':False,'user_approved':False,'dataset_promoted':False,'source_inspected_directly':True,'device':'CPU','threads':2,'lighting_note':'R4/R5 include provisional below-ceiling review sources; physical fixture design is pending. Older r1/r2 interiors were underexposed.'}
 for name in ['current_visual_status.json','slot_status_patch.json']:atomic(d/name,json.dumps(data,indent=2)+'\n')
 def link(p,label=None):
  p=Path(p)
  if not p.exists():return ''
  rel=p.relative_to(d).as_posix();return '<a href="'+html.escape(rel,quote=True)+'">'+html.escape(label or rel)+'</a>'
 tabs=[]
 if (d/'reference_preview.jpg').exists():tabs.append(('reference_preview.jpg','Original reference'))
 tabs.extend((p,f"r{current.get('revision')} render: {Path(f).stem}") for p,f in previews)
 if current.get('revision')==6:
  baseline=next((e for e in evidence if e['revision']==5),{})
  for f in baseline.get('frames',[]):
   if not (f.name.startswith('overview') or 'context' in f.name):continue
   out=d/f'candidate_r5_{f.stem}_preview.jpg'
   if out.exists():tabs.append((out.name,'r5 A baseline (same camera): '+f.stem))
 buttons=''.join('<button onclick="document.getElementById(\'panel\').src=\''+html.escape(p,quote=True)+'\'">'+html.escape(label)+'</button>' for p,label in tabs)
 table='<table><tr><th>Source revision</th><th>Actual source candidate</th><th>Evidence</th></tr>'
 for e in evidence:
  links=[link(e['job_path'],'job receipt'),link(e['receipt_path'],'frame source + SHA256')]+[link(f,f.name) for f in e['frames']]
  table+='<tr><td>r'+str(e['revision'])+'</td><td>'+html.escape(Path(e['source']).name)+'</td><td>'+' · '.join(x for x in links if x)+'</td></tr>'
 table+='</table>'
 useful=['scene_contract.json','preflight_layout.json','candidate_r1_native_inventory.json','candidate_r3_service_inventory.json','candidate_r5_support_audit.json','candidate_r1_visual_review.json','candidate_r2_visual_review.json','candidate_r5_visual_review.json','candidate_r5_floor_visible_surface_audit.json','candidate_r5_floor_metric_diagnosis.json','candidate_r6_metric_change.json','candidate_r6_metric_visual_review.json','candidate_r6_metric_floor_visible_surface_audit.json','candidate_r6_metric_ab_validation.json'];links=' · '.join(x for x in [link(d/n) for n in useful] if x)
 initial=previews[0][0] if previews else 'reference_preview.jpg';image_html='<img id="panel" src="'+html.escape(initial,quote=True)+'">' if (d/initial).exists() else ''
 body='<!doctype html><meta charset="utf-8"><title>'+scene+'</title><style>body{background:#17232b;color:#eee;font:15px system-ui;max-width:1100px;margin:28px auto}button{padding:10px;margin:4px}img{width:100%;object-fit:contain}a{color:#9dd8ff}td,th{padding:9px;text-align:left;border-bottom:1px solid #52606b}table{width:100%;font-size:13px}</style><h1>'+scene+'</h1><p>'+status+' · CPU2 threads · acceptance false</p><p>Latest saved candidate: '+html.escape(candidate.name)+((' · camera suite reviewed, major issues open' if review.get('review_complete') else ' · partial direct review, major issues open') if latest_reviewed else ' · visual review pending')+'</p><p>Displayed image source: '+html.escape(current.get('source','No exact-source rendered frames yet'))+'</p>'+buttons+image_html+table+'<p>Original source.png directly inspected. Metric reconstruction is estimated, not surveyed. Native shell and product batches are intermediate artifacts.</p><ul>'+''.join('<li>'+html.escape(x)+'</li>' for x in issues)+'</ul><p>'+links+'</p>'
 atomic(d/'progress.html',body);print(scene,status,len(frames),len(live_jobs),flush=True)
