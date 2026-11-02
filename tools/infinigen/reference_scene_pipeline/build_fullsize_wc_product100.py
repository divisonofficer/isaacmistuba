"""Native Infinigen full-tank product at adult SI dimensions; no object rescaling."""
import bpy,json,hashlib,sys,math
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'modules/infinigen'));sys.path.insert(0,str(Path(__file__).parent))
from infinigen.assets.objects.bathroom.toilet import ToiletFactory
from infinigen.core.util.math import FixedSeed
from wc_layout_checks import bounds,seat_measurement
from compact_wc_contract import mesh_geometry_hash
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/native_fullsize_wc100';D.mkdir(exist_ok=True);out=D/'product.blend';assert not out.exists();bpy.ops.wm.read_factory_settings(use_empty=True);seed=48712530
cfg={'size':.43,'width':.31,'height':.385,'size_mid':.625,'depth':.23,'tube_scale':.27,'thickness':.035,'extrude_height':.0125,'stand_depth':.21,'stand_scale':.78,'bottom_offset':1.0,'back_thickness':.02,'back_size':.19,'back_scale':.90,'seat_thickness':.005,'seat_size':.045,'has_seat_cut':False,'tank_width':.36,'tank_height':.37,'tank_size':.14,'tank_cap_height':.028,'tank_cap_extrude':.002,'cover_rotation':-1.15,'hardware_type':'button','hardware_radius':.015}
trials=[]
for i in range(4):
 for o in list(bpy.data.objects):bpy.data.objects.remove(o,do_unlink=True)
 f=ToiletFactory(seed)
 for name,value in cfg.items():setattr(f,name,value)
 with FixedSeed(seed):obj=f.create_asset()
 bpy.context.view_layer.update();assert max(abs(s-1) for s in obj.scale)<1e-6
 lo,hi=bounds(obj);measurement=seat_measurement(obj);dims=hi-lo;trials.append({'parameters':dict(cfg),'bbox_dimensions_m':list(dims),'seat_height_m':measurement['seat_height_m']});print('NATIVE_PRODUCT_TRIAL',i,list(dims),measurement['seat_height_m'],flush=True)
 # +X is native forward. Change factory SI construction parameters, never scale a product mesh.
 if abs(dims.x-.68)<.002 and abs(dims.y-.38)<.002 and .400<=measurement['seat_height_m']<=.420:break
 cfg['size']+=.68-dims.x;cfg['width']+=.38-dims.y;cfg['height']+=.410-measurement['seat_height_m']
else:raise AssertionError(trials)
obj.location.z-=lo.z;bpy.context.view_layer.update();bpy.context.view_layer.objects.active=obj;obj.select_set(True);bpy.ops.object.transform_apply(location=True,rotation=True,scale=False)
obj.name='NativeFullTankWC100';obj['asset_source']='Native Infinigen ToiletFactory,physical SI preset';obj['factory_seed']=seed;obj['native_scale']=True
for o in list(bpy.data.objects):
 if o!=obj:bpy.data.objects.remove(o,do_unlink=True)
def mat(name,color,rough,metal,ior):
 m=bpy.data.materials.new(name);m.use_nodes=True;bs=m.node_tree.nodes['Principled BSDF'];bs.inputs['Base Color'].default_value=(*color,1);bs.inputs['Roughness'].default_value=rough;bs.inputs['Metallic'].default_value=metal;bs.inputs['IOR'].default_value=ior;return m
ceramic=mat('WC100_glazed_porcelain',(.88,.875,.85),.13,0,1.45);metal=mat('WC100_satin_flush_button',(.48,.50,.52),.22,1,1.5);obj.data.materials.clear();obj.data.materials.append(ceramic);obj.data.materials.append(metal);hardware=obj.data.attributes.get('hardware');assert hardware and hardware.domain=='FACE'
for face,value in zip(obj.data.polygons,hardware.data):face.material_index=1 if value.value>.5 else 0
lo,hi=bounds(obj);assert max(abs(s-1) for s in obj.scale)<1e-6;bpy.ops.wm.save_as_mainfile(filepath=str(out));sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
(D/'contract.json').write_text(json.dumps({'prototype_source':str(out),'prototype_source_sha256':sha(out),'object':obj.name,'mesh_geometry_sha256':mesh_geometry_hash(obj.data),'factory_source':'modules/infinigen/infinigen/assets/objects/bathroom/toilet.py','factory_source_sha256':sha(R/'modules/infinigen/infinigen/assets/objects/bathroom/toilet.py'),'seed':seed,'factory_parameters':cfg,'parameter_trials':trials,'bbox_m':[list(lo),list(hi)],'bbox_dimensions_m':list(hi-lo),'seat':seat_measurement(obj),'scale':list(obj.scale),'vertices':len(obj.data.vertices),'faces':len(obj.data.polygons),'tank_included':True,'scope':'Actual complete native bowl/seat/cover/pedestal/tank/cap/flush-button geometry generated at physical SI size. No global object scaling. Not room/door/path/side clearance or plumbing/photorealism approval.'},indent=2))
