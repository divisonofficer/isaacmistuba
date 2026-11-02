"""Inspect actual curated USD assemblies; readiness labels do not certify visual suitability."""
import json,hashlib
from pathlib import Path
from pxr import Usd,UsdGeom,UsdShade
ROOT=Path(__file__).resolve().parents[3];manifest=ROOT/'assets/opticalnav_curated/moorelane_assets.json';m=json.loads(manifest.read_text());source=ROOT/m['source_usd'];ids={'moorelane_entry_door','moorelane_living_armchair_pair','moorelane_studio_fig'};selected=[a for a in m['assets'] if a['asset_id'] in ids];assert len(selected)==3
mask=Usd.StagePopulationMask()
for a in selected:mask.Add(a['source_path'])
stage=Usd.Stage.OpenMasked(str(source),mask);assert stage;cache=UsdGeom.BBoxCache(Usd.TimeCode.Default(),[UsdGeom.Tokens.default_,UsdGeom.Tokens.render,UsdGeom.Tokens.proxy],useExtentsHint=False);rows=[]
for a in selected:
 prim=stage.GetPrimAtPath(a['source_path']);assert prim;parts=[];materials=set();deps=[]
 for p in Usd.PrimRange(prim):
  if not p.IsA(UsdGeom.Mesh):continue
  mesh=UsdGeom.Mesh(p);counts=mesh.GetFaceVertexCountsAttr().Get() or [];points=mesh.GetPointsAttr().Get() or [];bound=UsdShade.MaterialBindingAPI(p).ComputeBoundMaterial()[0]
  if bound:materials.add(str(bound.GetPath()))
  parts.append({'path':str(p.GetPath()),'vertices':len(points),'triangles':sum(max(0,n-2) for n in counts),'bound_material':str(bound.GetPath()) if bound else None})
 box=cache.ComputeWorldBound(prim).ComputeAlignedRange();rows.append({'asset_id':a['asset_id'],'source_path':a['source_path'],'parts':parts,'actual_world_bounds_stage_units':[list(box.GetMin()),list(box.GetMax())],'material_paths':sorted(materials),'total_triangles':sum(p['triangles'] for p in parts),'visual_suitability':'unreviewed'})
d={'source_usd':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'meters_per_unit':UsdGeom.GetStageMetersPerUnit(stage),'up_axis':str(UsdGeom.GetStageUpAxis(stage)),'assets':rows,'scope':'Actual USD mesh/binding/bounds inventory only. Not visual acceptance. Glass sheets alone are not detailed door assemblies; native USD materials must be preserved,not substituted by legacy measured-material labels.'};ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';(ref/'curated_office_asset_probe.json').write_text(json.dumps(d,indent=2)+'\n');print(json.dumps(d,indent=2))
