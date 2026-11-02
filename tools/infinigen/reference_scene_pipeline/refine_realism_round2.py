"""Reject inflated cloth silhouettes; improve material visibility with plausible practical ratios."""
import bpy,math,random,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';source=base/'scene_candidate_r24.blend';out=base/'scene_candidate_r25.blend';assert not out.exists();before=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));lookup={o.get('program_key'):o for o in bpy.data.objects};changed=[]
for unit in (101,102):
 rng=random.Random(unit+2500)
 for tier,railz in enumerate((1.8,1.05)):
  for g in range(6):
   yc=-1.04+g*.22;angle=rng.uniform(-.26,.26);length=rng.uniform(.57,.64) if tier==0 else rng.uniform(.57,.66);phase=rng.uniform(0,6);key=f'{unit}_hanging_garment_{tier}_{g}';o=lookup[key];verts=[];rings=36;sides=48
   def transform(x,y,z):return (.28+math.cos(angle)*x-math.sin(angle)*y,yc+math.sin(angle)*x+math.cos(angle)*y,z)
   for j in range(rings):
    t=j/(rings-1);width=.055+(.13*min(t/.14,1))*(1-.10*t)
    for k in range(sides):
     theta=2*math.pi*k/sides;x=width*math.cos(theta)
     # Front/back cloth panels share gravity folds, retaining a small air gap.
     crease=(.010*math.sin(3*math.pi*x/max(width,.02)+phase+1.8*t)+.004*math.sin(7*math.pi*x/max(width,.02)-phase+3*t))*math.sin(math.pi*t)**.55
     y=(.004+.002*math.sin(math.pi*t))*math.sin(theta)+crease
     z=railz-.055-t*length-.010*math.sin(3*theta+phase)*t*t-.003*math.sin(8*t+theta)
     verts.append(transform(x,y,z))
   assert len(verts)==len(o.data.vertices)
   for v,co in zip(o.data.vertices,verts):v.co=co
   o.data.update();hem=lookup[f'{unit}_hem_{tier}_{g}'];points=verts[-sides:]+[verts[-sides]]
   for dst,co in zip(hem.data.splines[0].points,points):dst.co=(*co,1)
   for side in (-1,1):
    sleeve=lookup[f'{unit}_sleeve_{tier}_{g}_{side}'];sv=[]
    for j in range(12):
     t=j/11;cx=side*(.16+.055*t);cz=railz-.12-.19*t;radius=.035-.01*t
     for k in range(24):
      q=2*math.pi*k/24;sv.append(transform(cx+radius*math.cos(q),.006*math.sin(q)+.004*math.sin(5*q+t*3)*t,cz-.003*math.sin(3*q+t)))
    for v,co in zip(sleeve.data.vertices,sv):v.co=co
    sleeve.data.update()
   changed.append(o.name)
for o in bpy.data.objects:
 if o.get('program_key','').endswith('_folded_knit'):
  o.dimensions.z=.04;o.location.z-=.0125
for m in bpy.data.materials:
 if m.name.startswith('FineR1_garment_'):
  bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');bs.inputs['Specular IOR Level'].default_value=.25;bs.inputs['Sheen Weight'].default_value=.08
  # Multiply the actual constant input, preserving linked multi-scale colour.
  for n in m.node_tree.nodes:
   if n.type=='MIX_RGB' and not n.inputs[1].is_linked:
    rgba=n.inputs[1].default_value;n.inputs[1].default_value=(rgba[0]*.75,rgba[1]*.75,rgba[2]*.75,1);break
 if m.get('reference_pbr_kind')=='glazed_ceramic':
  bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');bs.inputs['Base Color'].default_value=(.72,.715,.70,1);bs.inputs['Coat Weight'].default_value=.12;bs.inputs['Coat Roughness'].default_value=.07
lights=[]
for o in bpy.data.objects:
 if o.type!='LIGHT':continue
 name=o.name
 if name.startswith('res03_area_') and any(t in name for t in ('ensuite','bathroom','laundry_wc')):o.data.energy=18;lights.append({'name':name,'watts':18})
 elif name.startswith('Realism_') and '_downlight_' in name:o.data.energy=8;o.data.size=.09;lights.append({'name':name,'watts':8})
 elif name.startswith('Realism_') and '_mirror_bar' in name:o.data.energy=8;o.data.size_y=.025;lights.append({'name':name,'watts':8})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==before
(ref/'realism_refinement_r25.json').write_text(json.dumps({'source':str(source),'source_sha256':before,'candidate':str(out),'reason':'r24 rendered garments still looked inflated and plastic; not accepted as fine.','changes':['Collapsed front/back cloth panels with shared gravity creases; flattened sleeves; thinner folded knits with preserved shelf clearance.','Lower cotton specular/sheens and restrained colour reflectance.','Reduced overly diffuse bathroom fill relative to narrow practical sources; ceramic substrate warm-white reflectance and thin glaze response.'],'garments_changed':len(changed),'lights':lights,'photorealism_accepted':False},indent=2));print('Saved r25; garments',len(changed),'lights',len(lights),flush=True)
