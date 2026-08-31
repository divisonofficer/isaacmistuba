#!/usr/bin/env python3
"""Prepare matched kitchen TextureCan repeat-scale A/B render requests."""
from __future__ import annotations

import argparse, copy, json, sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"modules"/"robomituba_bridge"/"src")]
from robomituba_bridge.camera_pose import matrix_to_legacy_flat, resolve_viewpoint_pose  # noqa: E402

def pose(x,z,yaw): return matrix_to_legacy_flat(resolve_viewpoint_pose((x,z,0),yaw,eye_height_m=1.45).camera_to_world_mitsuba)
def bsdf(mid,maps,repeat):
 root=ET.Element("bsdf",{"type":"twosided","id":f"kitchen_repeat_{repeat:g}"}); normal=ET.SubElement(root,"bsdf",{"type":"normalmap"})
 for parent,name,key,raw in ((normal,"normalmap","normal_gl",True),):
  tex=ET.SubElement(parent,"texture",{"name":name,"type":"bitmap"}); ET.SubElement(tex,"string",{"name":"filename","value":maps[key]}); ET.SubElement(tex,"boolean",{"name":"raw","value":"true"}); tr=ET.SubElement(tex,"transform",{"name":"to_uv"}); ET.SubElement(tr,"scale",{"x":str(repeat),"y":str(repeat)})
 pl=ET.SubElement(normal,"bsdf",{"type":"pplastic"}); ET.SubElement(pl,"float",{"name":"int_ior","value":"1.5000"})
 for name,key,raw in (("diffuse_reflectance","base_color",False),("alpha","roughness",True)):
  tex=ET.SubElement(pl,"texture",{"name":name,"type":"bitmap"}); ET.SubElement(tex,"string",{"name":"filename","value":maps[key]})
  if raw: ET.SubElement(tex,"boolean",{"name":"raw","value":"true"})
  tr=ET.SubElement(tex,"transform",{"name":"to_uv"}); ET.SubElement(tr,"scale",{"x":str(repeat),"y":str(repeat)})
 return root
def main():
 p=argparse.ArgumentParser(description=__doc__); p.add_argument("--scene-dir",type=Path,required=True);p.add_argument("--request",type=Path,required=True);p.add_argument("--registry",type=Path,required=True);p.add_argument("--out-dir",type=Path,required=True);a=p.parse_args()
 scene,out=a.scene_dir.resolve(),a.out_dir.resolve();out.mkdir(parents=True,exist_ok=True); reg={x['id']:x for x in json.loads(a.registry.read_text())['materials']}; rec=reg['texturecan_tiles_0042'];maps={k:str((a.registry.parent/v).resolve()) for k,v in rec['maps'].items()}
 baseline=scene/'structural_material_ab/render_scene_orphan_clean_baseline.xml'; template=json.loads(a.request.read_text()); views=[('overview',6.67,6.15,0),('floor_grazing',8.35,7.31,90)]; rows=[]
 for label,repeat,xml in [('baseline',None,baseline),('tile_x2',2,None),('tile_x4',4,None),('tile_x6',6,None)]:
  if repeat:
   root=ET.parse(baseline).getroot();root.insert(0,bsdf(rec['id'],maps,repeat))
   for shape in root.findall('.//shape'):
    shape_id=shape.get('id') or ''
    if shape_id == 'kitchen_0_0.floor' or shape_id == 'kitchen_0_0.wall' or shape_id.startswith('kitchen_0_0.wall__'):
     for ref in list(shape.findall('ref')):shape.remove(ref)
     ET.SubElement(shape,'ref',{'id':f'kitchen_repeat_{repeat:g}'})
   ET.indent(root,space='  ');xml=out/f'render_scene_kitchen_{label}.xml';ET.ElementTree(root).write(xml,encoding='utf-8',xml_declaration=True)
  for n,(view,x,z,yaw) in enumerate(views,1):
   q=copy.deepcopy(template);suffix=f'kitchen-repeat-v2-{label}-{n:02d}-{view}';frame=f'{scene.name}_{suffix.replace("-","_")}';job=f'opticalnav-{scene.name}-{suffix}';q.update({'request_id':suffix,'job_id':job,'frame_id':frame});q['scene_state'].update({'job_id':job,'frame_id':frame,'scene_snapshot_ref':str(xml.relative_to(ROOT)),'mitsuba_scene_ref':str(xml.relative_to(ROOT))});m=pose(x,z,yaw);q['robot_state']['base_pose']=m;q['camera_specs'][0]['camera_to_world']=m;q['camera_specs'][0]['extras']['render'].update({'path_spp':512,'polar_spp':256});q['render_settings'].update({'path_spp':512,'polar_spp':256});q['extras']['kitchen_repeat_ab']={'variant':label,'repeat':repeat,'view':view};path=out/f'{suffix}.json';path.write_text(json.dumps(q,indent=2)+'\n');rows.append({'variant':label,'repeat':repeat,'view':view,'job_id':job,'request':str(path)})
 (out/'kitchen_repeat_ab_index.json').write_text(json.dumps({'material_id':rec['id'],'target_shapes':['kitchen_0_0.floor','kitchen_0_0.wall'],'views':rows},indent=2)+'\n');print(json.dumps({'requests':len(rows),'out':str(out)},indent=2))
if __name__=='__main__':main()
