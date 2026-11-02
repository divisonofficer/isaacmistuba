"""Extract real USD assemblies with their original bound material networks and textures."""
import json,hashlib
from pathlib import Path
from pxr import Usd,UsdGeom,UsdShade,Sdf
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';probe=json.loads((ref/'curated_office_asset_probe.json').read_text());src=Path(probe['source_usd']);out=ref/'real_asset_candidates';out.mkdir(exist_ok=True);target=out/'moorelane_candidates.usdc';assert not target.exists();mask=Usd.StagePopulationMask()
for row in probe['assets']:mask.Add(row['source_path'])
stage=Usd.Stage.OpenMasked(str(src),mask);material_paths=set()
for p in stage.Traverse():
 for rel in p.GetRelationships():
  if rel.GetName().startswith('material:binding'):
   for path in rel.GetTargets():
    if path.IsPrimPath():material_paths.add(str(path))
assert material_paths
for path in material_paths:mask.Add(path)
stage=Usd.Stage.OpenMasked(str(src),mask);parts=[];dependencies={}
for p in stage.Traverse():
 if p.IsA(UsdGeom.Mesh):
  bound=UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial()[0];parts.append({'mesh':str(p.GetPath()),'material':str(bound.GetPath()) if bound else None,'binding_resolved':bool(bound),'authored_binding_targets':[str(t) for rel in p.GetRelationships() if rel.GetName().startswith('material:binding') for t in rel.GetTargets()]})
 for a in p.GetAttributes():
  val=a.Get()
  if isinstance(val,Sdf.AssetPath) and val.path:
   if val.path.startswith('opdef:'):continue
   dependencies[(val.path,val.resolvedPath)]={'authored':val.path,'resolved':val.resolvedPath,'exists':bool(val.resolvedPath) and Path(val.resolvedPath).is_file(),'attribute':str(a.GetPath())}
flat=stage.Flatten();assert flat.Export(str(target));report={'source_usd':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'extracted_usd':str(target),'extracted_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'assets':probe['assets'],'bound_meshes':parts,'unbound_meshes':[p for p in parts if not p['binding_resolved']],'material_count':len(material_paths),'texture_dependencies':list(dependencies.values()),'missing_dependencies':[x for x in dependencies.values() if not x['exists']],'native_material_networks_preserved':True,'visual_suitability':'not_reviewed','scope':'Actual source meshes,UVs,bindings and authored Houdini+UsdPreviewSurface material networks. No proxy geometry and no legacy measured-material reassignment. Must inspect importer output and license before scene use.'};(out/'extraction_manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'meshes':len(parts),'materials':len(material_paths),'dependencies':len(dependencies),'missing':len(report['missing_dependencies']),'output':str(target)}))
