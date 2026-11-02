"""Labelled lightweight review sheets from verified render receipts."""
import argparse,json,hashlib
from pathlib import Path
from PIL import Image,ImageDraw
p=argparse.ArgumentParser();p.add_argument('--renders',type=Path,required=True);a=p.parse_args();receipt=json.loads((a.renders/'render_receipt.json').read_text());frames=receipt['frames'];pages=[]
for start in range(0,len(frames),4):
 canvas=Image.new('RGB',(1024,824),'#eef1f5');draw=ImageDraw.Draw(canvas)
 for offset,frame in enumerate(frames[start:start+4]):
  path=Path(frame['path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==frame['sha256'];x=(offset%2)*512;y=(offset//2)*412
  with Image.open(path) as im:
   im=im.convert('RGB');im.thumbnail((512,384));canvas.paste(im,(x+(512-im.width)//2,y))
  draw.text((x+8,y+389),frame['name'],fill='#172336')
 output=a.renders/f'contact_{start//4+1:02}.jpg';canvas.save(output,quality=91,optimize=True);pages.append(str(output))
(a.renders/'contact_sheet_manifest.json').write_text(json.dumps({'source_sha256':receipt['source_sha256'],'pages':pages,'frame_count':len(frames),'scope':'Composition and major artifact review; full-resolution closeups separately inspected.'},indent=2));print(json.dumps(pages))
