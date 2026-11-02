"""Saved fixture fit/ceiling recess/light graph audit; no photo certification."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';S=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r84.blend';O=D/'living_downlights_saved_audit_r84.json';assert not O.exists();meta=json.loads((D/'realism_refinement_r84.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(S));dg=bpy.context.evaluated_depsgraph_get();ceiling=bpy.data.objects['living-room_0/0.ceiling'];e=ceiling.evaluated_get(dg);m=e.to_mesh();ct=BVHTree.FromPolygons([ceiling.matrix_world@v.co for v in m.vertices],[list(f.vertices) for f in m.polygons]);e.to_mesh_clear();errors=[];rows=[]
for r in meta['fixtures']:
 o=bpy.data.objects[r['object']];e=o.evaluated_get(dg);m=e.to_mesh();pts=[o.matrix_world@v.co for v in m.vertices];tree=BVHTree.FromPolygons(pts,[list(f.vertices) for f in m.polygons]);lo=Vector([min(p[k] for p in pts) for k in range(3)]);hi=Vector([max(p[k] for p in pts) for k in range(3)]);x,y=r['xy'];cz=r['ceiling_z'];body_dimensions=list(hi-lo);center=Vector((x,y,cz-.02));blocked=ct.ray_cast(center,Vector((0,0,1)),.03)[0];retained=ct.ray_cast(Vector((x+.06,y,cz-.02)),Vector((0,0,1)),.05)[0];trim=[]
 for dx,dy in [(-.035,-.035),(-.035,.035),(.035,-.035),(.035,.035)]:trim.append(tree.ray_cast(Vector((x+dx,y+dy,cz-.03)),Vector((0,0,1)),.05)[0] is not None)
 light=bpy.data.objects[r['area_light']];bb=[n for n in light.data.node_tree.nodes if n.type=='BLACKBODY'];em=next(n for n in light.data.node_tree.nodes if n.type=='EMISSION');ok=len(bb)==1 and bb[0].inputs['Temperature'].default_value==3200 and em.inputs['Color'].is_linked and abs(light.location.z-(cz-.009))<1e-5 and not light.data.cycles.is_portal
 checks={'native_faces_preserved':len(o.data.polygons)==6294,'dimensions_preserved':abs(body_dimensions[0]-.1048736)<1e-5 and abs(body_dimensions[1]-.1048736)<1e-5 and abs(body_dimensions[2]-.011)<1e-5,'body_top_fit':abs(hi.z-(cz+.004))<1e-5,'recess_clear_through_body_depth':blocked is None,'surrounding_ceiling_retained':retained is not None,'trim_covers_all_square_cutout_corners':all(trim),'warm_transport_light_below_fixture':ok}
 for k,v in checks.items():
  if not v:errors.append({'object':o.name,'reason':k})
 rows.append({'object':o.name,'checks':checks,'bounds':[list(lo),list(hi)],'transport_power':light.data.energy,'emission_node_strength':em.inputs['Strength'].default_value,'temperature_K':bb[0].inputs['Temperature'].default_value if bb else None});e.to_mesh_clear()
if len(rows)!=4:errors.append({'reason':'expected_four_fixtures'})
if not meta['coves']:errors.append({'reason':'no_living_cove_temperature_changes'})
if any(n in bpy.data.objects for n in meta['removed']):errors.append({'reason':'old_fixture_or_light_remains'})
h=hashlib.sha256(S.read_bytes()).hexdigest();assert h==meta['candidate_sha256'];O.write_text(json.dumps({'source':str(S),'source_sha256':h,'rows':rows,'errors':errors,'pass':not errors,'scope':'Four exact native envelopes,ceiling recess center/corner/retained-surface rays and3200K light graphs. Not full ceiling/fixture volume,driver housing,photometry,illumination quality or navigation certification.','photorealism_accepted':False},indent=2)+'\n');print('NATIVE_DOWNLIGHT_SAVED_AUDIT',len(errors),flush=True);assert not errors,errors
