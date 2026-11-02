"""Count each imported checkout pack's object-index silhouette in verification PNGs."""
import json
from pathlib import Path
from PIL import Image
import numpy as np
p=Path('/tmp/claude-0/s/codex_pkgs/pkg_c/S37')
rows=[]
for f in sorted((p/'masks').glob('PkgCProp_Pack*.png')):
 a=np.asarray(Image.open(f));rows.append({'mask':f.name,'visible_pixels':int((a>8).sum())})
n=sum(x['visible_pixels']>=24 for x in rows)
report={'pack_masks':rows,'count_at_least_24_pixels':n,'required':14,'passed':n>=14}
(p/'pixel_check.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
if not report['passed']:raise SystemExit('Fewer than 14 visibly countable checkout packs')
