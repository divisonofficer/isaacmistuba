"""Keep inspection HTML small by deduplicating embedded images into sibling files."""
import base64,hashlib,re
from pathlib import Path
IMAGE=re.compile(r'data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)')
def write_lightweight_inspection(path,document):
 path=Path(path);assets=path.parent/'inspection_assets';assets.mkdir(exist_ok=True)
 def replace(match):
  payload=base64.b64decode(match.group(2),validate=True);extension={'jpeg':'jpg','png':'png','webp':'webp'}[match.group(1)]
  name=hashlib.sha256(payload).hexdigest()+'.'+extension;target=assets/name
  if not target.exists():target.write_bytes(payload)
  else:assert target.read_bytes()==payload
  return 'inspection_assets/'+name
 compact=IMAGE.sub(replace,document);assert 'data:image/' not in compact
 temp=path.with_name(path.name+'.light.tmp');temp.write_text(compact);temp.replace(path)
 return {'html_bytes':path.stat().st_size,'embedded_html_bytes':len(document.encode()),'asset_count':len(set(IMAGE.findall(document)))}
