"""Independent shader ablations on the actual chair, before another room round."""
import bpy,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3]
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_breakout_chair_candidates/aac23_blue_wood_variant'
O=D/'surface_cause_probe';assert not O.exists();O.mkdir()
source=D/'review_studio.blend';source_sha=hashlib.sha256(source.read_bytes()).hexdigest()
views=[json.loads((D/'views.json').read_text())[0]]
(O/'views.json').write_text(json.dumps(views,indent=2))
rows=[];initial=None
for label in ['albedo_emission','normal_off','sheen_off','coat_off']:
    bpy.ops.wm.open_mainfile(filepath=str(source))
    mat=bpy.data.materials['BreakoutAAC23_authored_blue_native_fabric'];n,l=mat.node_tree.nodes,mat.node_tree.links
    bs=next(x for x in n if x.type=='BSDF_PRINCIPLED')
    if initial is None:
        initial={key:{'value':bs.inputs[key].default_value,'linked':bs.inputs[key].is_linked} for key in
                 ['Metallic','Roughness','IOR','Specular IOR Level','Coat Weight','Coat Roughness','Sheen Weight','Sheen Roughness']}
        initial['normal_maps']=[{'name':x.name,'strength':x.inputs['Strength'].default_value} for x in n if x.type=='NORMAL_MAP']
    if label=='albedo_emission':
        emission=n.new('ShaderNodeEmission');emission.inputs['Strength'].default_value=1
        if bs.inputs['Base Color'].is_linked:l.new(bs.inputs['Base Color'].links[0].from_socket,emission.inputs['Color'])
        else:emission.inputs['Color'].default_value=bs.inputs['Base Color'].default_value
        output=next(x for x in n if x.type=='OUTPUT_MATERIAL' and x.is_active_output)
        l.new(emission.outputs[0],output.inputs['Surface'])
    elif label=='normal_off':
        for link in list(bs.inputs['Normal'].links):l.remove(link)
    elif label=='sheen_off':
        assert not bs.inputs['Sheen Weight'].is_linked;bs.inputs['Sheen Weight'].default_value=0
    else:
        if not bs.inputs['Coat Weight'].is_linked and bs.inputs['Coat Weight'].default_value==0:continue
        for link in list(bs.inputs['Coat Weight'].links):l.remove(link)
        bs.inputs['Coat Weight'].default_value=0
    path=O/(label+'.blend');bpy.ops.wm.save_as_mainfile(filepath=str(path))
    rows.append({'label':label,'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
assert hashlib.sha256(source.read_bytes()).hexdigest()==source_sha
(O/'scope.json').write_text(json.dumps({'source':str(source),'source_sha256':source_sha,'source_unchanged':True,
    'initial_body_shader':initial,'variants':rows,'photorealism_accepted':False,
    'scope':'Same actual product geometry,camera and diagnostic lighting. Emission-only BaseColor reveals unlit albedo; normal/sheen/optional-coat individually disabled. These are diagnostic renders, not scene candidates or source101 modifications.'},indent=2))
print('AAC23_SURFACE_CAUSE_PROBES_SAVED',len(rows),flush=True)
