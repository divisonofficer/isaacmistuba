"""Experimental source66 branch: ceramic-glass hob with printed zones and controls;no promotion."""
import bpy,bmesh,json,hashlib,math
from pathlib import Path
from mathutils import Matrix
root=Path('/jarvis/project/robomituba');base=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r66.blend';out=base/'scene_candidate_r67.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
def mat(name,color,rough):
 m=bpy.data.materials.new(name);m.use_nodes=True;p=m.node_tree.nodes.get('Principled BSDF');p.inputs['Base Color'].default_value=(*color,1);p.inputs['Roughness'].default_value=rough;p.inputs['Metallic'].default_value=0;p.inputs['IOR'].default_value=1.5;return m
ink=mat('Induction67_ceramic_print',(.33,.35,.36),.38);glass=mat('Induction67_black_ceramic_glass',(.009,.012,.014),.13);p=glass.node_tree.nodes.get('Principled BSDF');p.inputs['Coat Weight'].default_value=.25;p.inputs['Coat Roughness'].default_value=.1
for parent in [o for o in bpy.data.objects if o.type=='MESH' and 'HomeKitchenRunFactory' in o.name]:
 me=parent.data;ringfaces=[p for p in me.polygons if p.material_index==6];ringids={i for p in ringfaces for i in p.vertices};assert len(ringids)==160 and len(ringfaces)==88
 hobfaces=[p for p in me.polygons if p.material_index==5];hobids={i for p in hobfaces for i in p.vertices};assert len(hobfaces)==6 and len(hobids)==8;vs=[me.vertices[i].co for i in hobids];lo=[min(v[k] for v in vs) for k in range(3)];hi=[max(v[k] for v in vs) for k in range(3)];assert abs(hi[2]-.903)<1e-6;cy=(lo[1]+hi[1])/2
 def sig(exclude):return hashlib.sha256(repr(sorted((tuple(sorted(tuple(round(c,7) for c in me.vertices[i].co) for i in p.vertices)),me.materials[p.material_index].name,p.use_smooth) for p in me.polygons if not any(i in exclude for i in p.vertices))).encode()).hexdigest()
 before=sig(ringids|hobids);me.materials.append(glass);gi=len(me.materials)-1
 for p in hobfaces:p.material_index=gi
 bm=bmesh.new();bm.from_mesh(me);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[bm.verts[i] for i in ringids],context='VERTS');bm.to_mesh(me);bm.free();me.update();newhobids={i for p in me.polygons if p.material_index==gi for i in p.vertices};assert sig(newhobids)==before
 verts=[];faces=[];z=hi[2]+.000025
 def quad(points):
  start=len(verts);verts.extend((x,y,z) for x,y in points);faces.append(tuple(range(start,start+len(points))))
 def line(x0,y0,x1,y1,width):
  dx=x1-x0;dy=y1-y0;length=math.hypot(dx,dy);nx=-dy/length*width/2;ny=dx/length*width/2;quad([(x0+nx,y0+ny),(x0-nx,y0-ny),(x1-nx,y1-ny),(x1+nx,y1+ny)])
 def arc(x,y,rad,width,start=0,end=math.tau,segments=128):
  for k in range(segments):
   a=start+(end-start)*k/segments;b=start+(end-start)*(k+1)/segments
   quad([(x+(rad-width/2)*math.cos(a),y+(rad-width/2)*math.sin(a)),(x+(rad+width/2)*math.cos(a),y+(rad+width/2)*math.sin(a)),(x+(rad+width/2)*math.cos(b),y+(rad+width/2)*math.sin(b)),(x+(rad-width/2)*math.cos(b),y+(rad-width/2)*math.sin(b))])
 zones=[]
 for x,dy,rad in [(.18,-.15,.08),(.18,.15,.07),(.39,-.15,.07),(.39,.15,.085)]:arc(x,cy+dy,rad,.0012);zones.append({'center':[x,cy+dy],'radius_m':rad})
 # Four non-emissive zero indicators,plus/minus and an open-circle power glyph.
 for y in [cy-.105,cy-.035,cy+.035,cy+.105]:
  x=.532;dx=.005;dy=.003;w=.0007
  for a,b,c,d in [(x-dx,y-dy,x+dx,y-dy),(x-dx,y+dy,x+dx,y+dy),(x-dx,y-dy,x-dx,y+dy),(x+dx,y-dy,x+dx,y+dy)]:line(a,b,c,d,w)
 arc(.532,cy-.235,.008,.001,start=.35,end=math.tau-.35,segments=64);line(.532,cy-.235,.543,cy-.235,.001)
 for y in [cy+.18,cy+.23]:line(.532,y-.005,.532,y+.005,.001)
 line(.527,cy+.23,.537,cy+.23,.001)
 assert all(lo[0]<=x<=hi[0] and lo[1]<=y<=hi[1] for x,y,_ in verts),'print outside glass footprint'
 mesh=bpy.data.meshes.new('Induction67_print_'+parent['program_key']);mesh.from_pydata(verts,[],faces);mesh.update();o=bpy.data.objects.new(mesh.name,mesh);bpy.context.collection.objects.link(o);o.parent=parent;o.matrix_parent_inverse=Matrix.Identity(4);o.matrix_basis=Matrix.Identity(4);mesh.materials.append(ink);o['audit_kind']='detail';o['program_key']=parent['program_key']+'__detail__induction_print'
 rows.append({'kitchen':parent.name,'removed_metal_disc_vertices':160,'unchanged_nonhob_signature':before,'glass_bounds_local':[lo,hi],'print_offset_above_glass_m':.000025,'ring_line_width_m':.0012,'zones':zones,'controls':'four neutral zero indicators,plus/minus,power;nonemissive generic unbranded print','scope':'Thin 2D print geometry intentional;not a closed 3D part. Existinghob footprint andother kitchen geometry retained.'})
assert len(rows)==2;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));(ref/'realism_refinement_r67.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'candidate':str(out),'base_status':'r66 refrigerator is still provisional;this is experimental branch,not acceptance','changes':rows,'photorealism_accepted':False,'requires':'four saved-source gates,same-camera A/B against66 andindependent review'},indent=2));print('Saved',out,flush=True)
