"""Require all-eight saved-source WC access evidence before rendering new full suites."""
import hashlib,json
from pathlib import Path
T=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def validate_access_reports(main,side,expected_keys,source_sha):
 assert len(expected_keys)==8 and len(set(expected_keys))==8,'Expected eight unique bathrooms'
 for report in [main,side]:
  assert report['source_sha256']==source_sha,'Stale bathroom source'
  assert report['pass'] is True,'Bathroom access report failed'
  assert len(report['records'])==8 and {r['key'] for r in report['records']}==set(expected_keys),'Incomplete bathroom coverage'
 for r in main['records']:
  assert r['pass'] and r['native_geometry_identity'] and r['tank_included'],r['key']
  assert max(abs(v-1) for v in r['scale'])<1e-6,r['key']
  assert .37<r['width_m']<.39 and .65<r['depth_m']<.70 and .400<=r['seat_height_m']<=.420,r['key']
  assert min(r['side_left_m'],r['side_right_m'])>=.4 and r['path_min_clear_width_m']>=.6-1e-5,r['key']
  assert r['door_sweep_wc_overlap_m2']<1e-8 and all(x['area_m2']<1e-8 for x in r['door_sweep_fixture_tests']),r['key']
  rays=r['actual_aperture_ray_tests'];assert len(rays)==28 and not any(x['blocked'] for x in rays),r['key']
 for r in side['records']:
  assert r['pass'],r['key']
  for name in ['left','right']:
   hit=r[name];assert hit['distance_m'] is None and hit.get('no_selected_surface_within_8m') or hit['distance_m'] is not None and hit['distance_m']>=.4,r['key']
def require_current_bathroom_access(ref,revision,source_sha):
 meta=json.loads((ref/f'realism_refinement_r{revision}.json').read_text())
 if 'wc_access100' not in meta:return {'required':False,'scope':'No authored full-size native WC contract in this historical source.'}
 assert meta['candidate_sha256']==source_sha,'Stale native WC metadata'
 paths=[ref/f'bathroom_access_r{revision}_saved_audit.json',ref/f'bathroom_access_r{revision}_side_rays.json'];main,side=[json.loads(p.read_text()) for p in paths];keys=[r['key'] for r in meta['wc_access100']['records']];validate_access_reports(main,side,keys,source_sha)
 assert main['helper_sha256']==sha(T/'bathroom_access_contract100.py'),'Stale bathroom access helper'
 assert main['auditor_sha256']==sha(T/f'audit_bathroom_access{revision}_saved.py'),'Stale saved bathroom auditor'
 return {'required':True,'bathrooms':keys,'reports':[{'path':str(p),'sha256':sha(p)} for p in paths],'scope':'Saved native products,sweeps,explicit600mm routes,224aperture rays andrealdoor-inclusive side rays. No RGB orwhole-scene acceptance.'}
