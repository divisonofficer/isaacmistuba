"""Source-bound gallery; rendering does not imply visual acceptance."""
from pathlib import Path
import json,hashlib,html
from PIL import Image
root=Path(__file__).resolve().parents[3];p=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/full_suite_r108_gpu5';job=json.loads((p/'job.json').read_text());assert job.get('exit_code')==0,job['phase']
views=json.loads(Path(job['views']).read_text());assert len(views)==21
receipt=json.loads((p/'candidate/render_receipt.json').read_text());assert receipt['source']==job['source'];assert receipt['source_sha256']==hashlib.sha256(Path(job['source']).read_bytes()).hexdigest();assert receipt.get('source_unchanged') is True;rows=[];frames=[]
for v in views:
 src=p/'candidate'/(v['name']+'.png');assert src.exists();digest=hashlib.sha256(src.read_bytes()).hexdigest();assert next(f for f in receipt['frames'] if f['name']==v['name'])['sha256']==digest;dst=p/(v['name']+'.jpg');im=Image.open(src).convert('RGB');im.thumbnail((1280,1280));im.save(dst,quality=87)
 frames.append({'name':v['name'],'sha256':digest,'image':str(src.relative_to(p))})
 rows.append('<figure><a href="candidate/'+html.escape(src.name)+'"><img loading="lazy" src="'+html.escape(dst.name)+'"></a><figcaption>'+html.escape(v['name'])+'</figcaption></figure>')
(p/'gallery_evidence.json').write_text(json.dumps({'source':job['source'],'source_sha256':hashlib.sha256(Path(job['source']).read_bytes()).hexdigest(),'frames':frames,'visual_review_complete':False,'accepted':False},indent=2))
(p/'report.html').write_text('<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Office108 all rooms</title><style>body{font:16px/1.6 system-ui;margin:auto;max-width:1400px;padding:24px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:18px}figure{margin:0}img{width:100%}</style><h1>Office108 · all21 views</h1><p>Latest draft108; render complete, full visual/independent review pending. No adoption or dataset promotion. External JPEG previews; click for original PNG.</p><div class="grid">'+''.join(rows)+'</div></html>')
print(p/'report.html')
