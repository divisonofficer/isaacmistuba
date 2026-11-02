"""User usage-realism correction: differentiated workstation states, native props.
No wall/material noise or lighting change; physical/render gates remain separate.
"""
import bpy
import hashlib
import json
import math
from pathlib import Path
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

ROOT=Path(__file__).resolve().parents[3]
D=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
P=D/'usage108_products'
B=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
S,O=B/'scene_candidate_r105.blend',B/'scene_candidate_r108_draft.blend'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def raw_bounds(objects, matrices):
    points=[matrices[obj]@v.co for obj in objects for v in obj.data.vertices]
    return (Vector(tuple(min(p[k] for p in points) for k in range(3))),
            Vector(tuple(max(p[k] for p in points) for k in range(3))))


def support_tree(obj):
    points=[obj.matrix_world@v.co for v in obj.data.vertices]
    expected_z=obj.matrix_world.translation.z+.75
    faces=[tuple(f.vertices) for f in obj.data.polygons
           if all(abs(points[i].z-expected_z)<.001 for i in f.vertices)]
    assert len(faces)>=4,(obj.name,'Native desk top surfaces missing')
    return BVHTree.FromPolygons(points,faces)


def main():
    assert not O.exists()
    audit=json.loads((P/'saved_source_audit.json').read_text());assert audit['pass']
    studio=P/'review_studio.blend';assert sha(studio)==audit['source_sha256']
    rows=json.loads((P/'review_scope.json').read_text())['assets']
    before=sha(S)
    bpy.ops.wm.open_mainfile(filepath=str(S))
    desks={str(o.get('program_key')):o for o in bpy.context.scene.objects
           if o.type=='MESH' and str(o.get('program_key','')).startswith('pod_')
           and '_chair' not in str(o.get('program_key','')) and len(o.get('seats',[]))==4}
    assert len(desks)==6, list(desks)
    desk_matrices={k:o.matrix_world.copy() for k,o in desks.items()}
    # Read native source mesh data. This avoids evaluating unrelated high-poly plants;
    # final source-bound checks must still evaluate modifiers after the draft is saved.
    trees={k:support_tree(o) for k,o in desks.items()}
    prototypes={};native_basis={}
    for row in rows:
        with bpy.data.libraries.load(str(studio),link=False) as (src,dst):
            dst.objects=row['objects']
        objects=dst.objects
        for o in objects:
            bpy.context.scene.collection.objects.link(o)
        matrices=[o.matrix_world.copy() for o in objects]
        for o,matrix in zip(objects,matrices):
            o.parent=None;o.matrix_world=matrix
        prototypes[row['id']]=objects
        native_basis[row['id']]=[o.matrix_world.copy() for o in objects]
    notebook_ids=[r['id'] for r in rows if 'Notebook' in next(
        e['name'] for e in json.loads((P/'asset_manifest.json').read_text())['assets'] if e['id']==r['id'])]
    mug_ids=[r['id'] for r in rows if r['id'] not in notebook_ids]
    assert len(notebook_ids)==2 and len(mug_ids)==2
    chair_changes=[];station_rows=[];props=[]
    for desk_index,(key,desk) in enumerate(sorted(desks.items())):
        matrix=desk_matrices[key]
        for seat_index,seat in enumerate(desk['seats']):
            index=desk_index*4+seat_index
            state=['empty','organized','active','away','active','organized'][index%6]
            side=1 if seat[0]>0 else -1
            y=float(seat[1])
            chair=next(o for o in bpy.context.scene.objects if o.get('program_key')==key+f'_chair{seat_index}')
            original=chair.matrix_world.copy()
            # Small, purposeful differences; empty chair tucked in, away chair pulled out.
            setback={'empty':-.035,'organized':.015,'active':.045,'away':.09}[state]
            delta=matrix.to_3x3()@Vector((side*setback, .018*((index%3)-1),0))
            angle=math.radians([-5,3,7,-8,4,0][index%6])
            pivot=original.translation
            transform=Matrix.Translation(delta)@Matrix.Translation(pivot)@Matrix.Rotation(angle,4,'Z')@Matrix.Translation(-pivot)
            chair_key=key+f'_chair{seat_index}'
            assembly={o for o in bpy.context.scene.objects if str(o.get('program_key',''))==chair_key or str(o.get('program_key','')).startswith(chair_key+'_')}
            for o in list(assembly):assembly.update(o.children_recursive)
            roots=[o for o in assembly if o.parent not in assembly]
            matrices={o:o.matrix_world.copy() for o in roots}
            for member in roots:member.matrix_world=transform@matrices[member]
            chair_changes.append({'object':chair.name,'key':chair['program_key'],'assembly_objects':[o.name for o in assembly],'state':state,'world_delta_m':list(delta),'yaw_delta_deg':math.degrees(angle),'before_matrix':[list(v) for v in original],'after_matrix':[list(v) for v in transform@original]})
            selected=[]
            if state in ['active','organized']:
                selected.append((notebook_ids[index%2],side*.60,y+.25,'notebook'))
            if state=='active':
                selected.append((mug_ids[(index//2)%2],side*.61,y-.34,'mug'))
            station_rows.append({'desk':key,'seat_index':seat_index,'state':state,'native_props':[x[3] for x in selected]})
            for asset_id,x,yy,role in selected:
                source_objects=prototypes[asset_id]
                objects=[o.copy() for o in source_objects]
                rotation=matrix.to_quaternion().to_matrix().to_4x4()@Matrix.Rotation(math.radians([-11,7,0,14][index%4]),4,'Z')
                rotated_matrices={o:rotation@basis for o,basis in zip(objects,native_basis[asset_id])}
                for o in objects:
                    bpy.context.scene.collection.objects.link(o)
                    o.parent=None
                lo,hi=raw_bounds(objects,rotated_matrices)
                target=matrix@Vector((x,yy,0))
                # Ray actual source desk triangles rather than hard-code tabletop height.
                hit,normal,face,distance=trees[key].ray_cast(Vector((target.x,target.y,3)),Vector((0,0,-1)),4)
                assert hit is not None and normal.z>.9,(key,role,'No upward support')
                shift=Vector((target.x-(lo.x+hi.x)/2,target.y-(lo.y+hi.y)/2,hit.z+.0005-lo.z))
                final_matrices={o:Matrix.Translation(shift)@rotated_matrices[o] for o in objects}
                for j,o in enumerate(objects):
                    o.matrix_world=final_matrices[o]
                    o.name=f'Usage108_{index}_{role}_{j}'
                    o['program_key']=f'usage108_{key}_{seat_index}_{role}'
                    o['original_asset_id']=asset_id
                    o['support_object']=desk.name
                    o['audit_kind']='furniture'
                    o['reference_scene_owner']='commercial_office_floor_02'
                # Use the exact assigned matrices; Blender dependency-graph cached
                # matrix_world can lag an RNA location edit until an expensive update.
                points=[final_matrices[o]@v.co for o in objects for v in o.data.vertices]
                low=min(p.z for p in points)
                # Multiple raw source surface samples catch off-edge and uneven support.
                test_points=[p for p in points if p.z<low+.002]
                gaps=[]
                for p in test_points[::max(1,len(test_points)//80)]:
                    support,n,_,_=trees[key].ray_cast(Vector((p.x,p.y,p.z+.01)),Vector((0,0,-1)),.1)
                    if support is None or n.z<=.9:
                        rejection={'desk':key,'role':role,'asset_id':asset_id,'target_world_m':list(target),'failed_sample_m':list(p),'native_rotated_bbox_m':[list(lo),list(hi)],'assigned_shift_m':list(shift),'top_hit_m':list(hit),'normal':list(n) if n else None}
                        (D/'usage108_support_rejection.json').write_text(json.dumps(rejection,indent=2)+'\n')
                        raise AssertionError((key,role,'support footprint leaves tabletop'))
                    gaps.append(p.z-support.z)
                assert gaps and min(gaps)>-.00001
                props.append({'desk':key,'station':index,'role':role,'asset_id':asset_id,'objects':[o.name for o in objects],'native_geometry_uv_unchanged':True,'source_basis_preserved_up_to_rigid_pose':True,'sampled_raw_support_min_gap_m':min(gaps),'sampled_raw_support_max_gap_m':max(gaps),'sample_count':len(gaps)})
    for objects in prototypes.values():
        for o in objects:bpy.data.objects.remove(o,do_unlink=True)
    # Native prototype images are already packed and byte-audited in the studio.
    # Existing source image dependencies remain untouched.
    bpy.ops.wm.save_as_mainfile(filepath=str(O))
    assert sha(S)==before
    report={'source':str(S),'source_sha256':before,'draft':str(O),'draft_sha256':sha(O),'station_states':station_rows,'chair_changes':chair_changes,'native_props':props,'new_cables_outlets_trays_added':False,'materials_lights_cameras_unchanged':True,'status':'UNACCEPTED_USAGE_DRAFT','photorealism_accepted':False,'dataset_promoted':False,'scope':'Native products with rigid poses, varying chair poses and sampled raw desk support only. Evaluated collision/navigation, individual monitor/keyboard pose, real cable/power hardware and matchedRGB still required.'}
    (D/'usage108_draft_build.json').write_text(json.dumps(report,indent=2)+'\n')
    print('USAGE108_DRAFT_SAVED',len(chair_changes),'chairs',len(props),'native props',flush=True)


if __name__=='__main__':main()
