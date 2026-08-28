# `out/` 정리 조사 리포트

조사일: 2026-08-18  
범위: `/jarvis/project/robomituba/out`  
원칙: 이번 조사는 읽기 전용이며 파일을 삭제하거나 이동하지 않았다.

## 결론 요약

`out/`은 하나의 산출물 디렉터리가 아니라 다음 네 종류가 섞인 작업 공간이다.

1. OpticalNav 프로젝트의 재사용 가능한 입력/메타데이터와 렌더·export 결과
2. Infinigen 원본 import 및 중간 staging/backup/cache
3. 독립적인 IR/BSDF/pBRDF 실험 결과
4. daemon/cache/debug/scratch 임시 결과

가장 먼저 정리할 후보는 이름으로 상태가 명확한 `.retired`, 오래된 smoke/debug, 비어 있는 디렉터리다. 반대로 `out/opticalnav/opticalnav-v0.2/scenes`, `dataset.json`, `episodes`, `splits`, `exports`, `render_ledger.sqlite3`는 현재 코드가 직접 참조하므로 보존을 기본값으로 둔다.

## 최상위 구조 및 1차 판정

| 경로 | 역할/관찰 | 1차 판정 |
|---|---|---|
| `bridge_jobs/` | 프레임 단위 RenderRequest/observation job. 2026-08-12까지 갱신 | 보존 또는 별도 archive 정책 필요 |
| `bridge_jobs_archive/` | 과거 job archive | archive manifest와 현재 export 참조 확인 후 후보 |
| `infinigen_imports/` | Infinigen import 원본, mesh/texture, scene manifest, authoring map, staging | 보존하되 상태별 하위 정리 |
| `infinigen_audits/` | Infinigen material/UV/pBRDF audit JSON | 감사 이력으로 보존; 중복 backup만 검토 |
| `opticalnav/` | OpticalNav-v0.2 프로젝트 및 asset library | 핵심 보존 대상 |
| `ir_dataset/` | IR dataset 작업본과 queue/QC 상태 | 버전별 보존/폐기 결정 필요 |
| `ir_dataset_exports/` | IR export bundle | 검증된 export만 보존, 나머지는 후보 |
| `ir_principled/` | Blender/Principled IR 실험 결과 | 실험 종료 여부 확인 후 후보 |
| `discrete_band_infinigen_2026-07-14/` | 날짜가 붙은 Infinigen discrete-band staging/render 입력 | OpticalNav 참조 확인 후 archive 후보 |
| `discrete_band_bridge_2026-07-18/`, `discrete_band_scene_2026-07-15/` | discrete-band XML/build/assembly 결과 | 재현 필요 없으면 archive 후보 |
| `bsdf_compare/`, `bsdf_compare_batch/`, `compare_measured_vs_analytic_vp039_h240/` | BSDF 비교 실험 | 결과 보고서/대표 이미지 확인 후 후보 |
| `spatial_pbr/`, `spatial_pbr_ab/`, `sv_polartexture_feasibility/` | spatial pBR 및 polarization feasibility 실험 | 실험 보존 기간 정책 필요 |
| `_polar_debug_alltargets/`, `_polar_debug_oldtargets/`, `_smoke_selected_cam_multimodal/` | debug/smoke 산출물 | 재현 로그가 필요 없으면 우선 삭제 후보 |
| `control_plane_cache/`, `texture_cache/` | 재생성 가능한 cache | 프로세스 중인지 확인 후 삭제 후보 |
| `scratchpad/`, `skill_staging/`, `test_dict/` | 임시/테스트 작업 | 내용 확인 후 우선 정리 후보 |
| `exported/`, `exports/`, `material_previews/`, `hpbrdf_compressed/` | 일반 export/preview/압축 데이터 | 사용처와 원본 보유 여부 확인 |
| `moorelane_render_stills/`, `moorelane_usd_report/` | scene-specific 결과/보고서 | 보고서 보존 여부 확인 |
| `notion_upload_bundle_2026-02-13*` | 업로드 bundle 및 tar.gz | 업로드 성공 확인 후 삭제 후보 |

## OpticalNav 구조

`out/opticalnav/opticalnav-v0.2/`에는 다음 항목이 있다.

```text
opticalnav-v0.2/
├── README.md, dataset_card.md, dataset.json
├── scenes/                 # 60개 이상 scene directory; authoring/IR/OpticalNav 입력
├── episodes/               # episode 정의
├── splits/                 # train/validation 등의 split
├── exports/                # 날짜/실험별 dataset export와 staging
├── graph_render_batches/   # 2026-05~07의 다수 batch JSON
├── render_ledger.sqlite3   # 약 163 MiB, 2026-08-18 갱신
├── thumbnails/             # scene/asset thumbnail
├── docs/
├── evaluation/             # 현재 비어 있음
├── observations/           # 현재 비어 있음
└── render_batches/         # 현재 비어 있음
```

`dataset.json`은 generation version을 `opticalnav-v0.2`로 기록하고, Infinigen scene 및 기존 glass/cornell scene을 함께 열거한다. 따라서 `scenes/` 아래 날짜가 오래된 디렉터리라도 deprecated라고 단정할 수 없다. 특히 현재 코드가 다음 경로들을 직접 기본값/입력으로 사용한다.

- `apps/backfill_ir_scene_statistics.py` → `scenes/`
- `apps/material_pipeline.py` → `scenes/`
- `apps/export_opticalnav_wizard.py` → `render_ledger.sqlite3`
- `apps/export_scene_to_usd.py`, `apps/bake_opticalnav_asset_thumbnails.py` → OpticalNav project
- `docs/ir_principled_dataset_v1.md` → 특정 `scenes/<scene>__ir_semantic_lod_v1`

### OpticalNav 보존/정리 기준

| 대상 | 권고 |
|---|---|
| `dataset.json`, `dataset_card.md`, `README.md`, `episodes/`, `splits/` | 보존 |
| `scenes/`의 일반 scene 및 `__ir_semantic_lod_v1` scene | authoring map/export 참조를 역색인한 뒤 보존 또는 scene 단위 폐기 |
| `render_ledger.sqlite3` | 보존. 삭제 시 export wizard/렌더 이력 기능이 손상될 수 있음 |
| `exports/export-*/` | `export_status.json`과 외부 업로드/검증 결과를 확인한 뒤 중복 export만 삭제 |
| `graph_render_batches/*.json` | ledger와 export가 완결된 batch만 장기 보존하지 않아도 됨. 다만 재현/감사에 필요하면 manifest만 남길 수 있음 |
| `thumbnails/` | scene/asset 재생성 가능 여부 확인 후 캐시로 분류 가능 |
| 비어 있는 `evaluation/`, `observations/`, `render_batches/` | 기능상 참조가 없다면 디렉터리 제거 가능. 단, 런처가 생성 전제를 갖는지 확인 |
| `asset_library/` | `asset_readiness.json`, audit JSON, `catalogs/`는 authoring 입력에 가까우므로 보존 |

## Infinigen imports 구조

`out/infinigen_imports/`는 단일 세대가 아니다.

```text
infinigen_imports/
├── kr_<id>_<scene>/                         # import 결과: meshes/textures/scene_manifest 등
├── kr_<id>_<scene>.backup.<timestamp>/      # 교체 전 backup
├── kr_<id>_<scene>...staging.<timestamp>/   # 진행 중/실패 가능성이 있는 staging
├── <name>__authoring_map.json               # OpticalNav authoring map; import mesh를 참조
├── _smoketest/                               # 작은 import smoke test
├── full/, indoor_seed2/, indoor_seed3/, indoor_seed4/
├── _external/                                # semantic LOD 등 외부/해시 캐시 참조 대상
└── .retired/<timestamp>/                     # 명시적으로 retired 된 import
```

관찰된 파일 유형은 `obj` 11,416개, `png` 9,666개, `mtl` 8,073개, `glb` 7,970개, `json` 3,820개, lock 45개 수준이다. 즉 `.obj/.mtl/.glb`는 서로 대체 관계라고 가정하면 안 된다. authoring map에는 `source_ref`, `glb_ref`, `fallback_obj_ref`가 함께 기록되는 경우가 있다.

### 현재성 신호

- 2026-08-18 생성/갱신된 `infinigen_single_room_*_20260818_v*` 및 대응 scene은 최신 import 계열로 보인다.
- `kr_...backup.20260818T...` 4개와 `kr_...staging.20260818T...` 1개가 있다. 이름상 정리 후보지만, 동일 scene의 최신 정식 디렉터리와 authoring map 참조를 비교하기 전에는 삭제하지 않는다.
- `.retired/20260814T0545Z/`에는 bedroom/living-room staging 및 import가 있다. retired라는 명시적 상태 때문에 가장 강한 삭제 후보지만, OpticalNav `scenes/`의 authoring map이 이 경로를 참조하는지 먼저 확인한다.
- `_smoketest/`는 작은 mesh와 `scene_manifest.json`으로 구성되어 있어 운영 입력이 아니라 테스트 fixture일 가능성이 높다.
- `full/`, `indoor_seed2/3/4` 및 오래된 `kr_202606*`는 OpticalNav dataset의 과거 scene 목록과 실제로 연결되어 있을 수 있다.
- 45개 lock 파일은 진행 중인 import를 나타낼 수 있으므로 lock이 남아 있는 scene은 삭제 금지. 해당 프로세스가 종료되고 lock이 stale인지 확인해야 한다.

### Infinigen 정리 우선순위

1. `.retired/` 전체를 참조 검사하고, 참조가 없으면 별도 archive 또는 삭제.
2. `.backup.*`와 `.staging.*`를 동일 scene의 정식 디렉터리와 `scene_manifest.json`/authoring map으로 비교. 성공적으로 승격된 staging만 삭제.
3. `_smoketest/`는 테스트가 현재 필요한지 확인 후 삭제.
4. 오래된 scene은 `out/opticalnav/opticalnav-v0.2/scenes/` 및 `dataset.json`, 모든 `__authoring_map.json`, export manifest에서 역참조를 확인한 후 scene 단위로 정리.
5. `.obj/.mtl`를 `.glb`와 일괄 비교해 삭제하지 않는다. `fallback_obj_ref`가 존재하는 동안은 OBJ가 재현성/호환성 자산일 수 있다.

## 즉시 삭제 후보와 보류 후보

### 참조 검증 후 바로 정리해도 될 가능성이 높은 것

- `out/infinigen_imports/.retired/`의 명시적 retired 세대
- `out/infinigen_imports/_smoketest/`
- `_polar_debug_alltargets/`, `_polar_debug_oldtargets/`, `_smoke_selected_cam_multimodal/`
- 비어 있는 `out/opticalnav/opticalnav-v0.2/evaluation/`, `observations/`, `render_batches/`
- 실행 중이 아님이 확인된 `control_plane_cache/`, `texture_cache/`
- `scratchpad/`, `skill_staging/`, `test_dict/`의 임시 파일

### 삭제 전 반드시 확인할 것

- `out/opticalnav/opticalnav-v0.2/scenes/`
- `out/opticalnav/opticalnav-v0.2/render_ledger.sqlite3`
- `out/opticalnav/opticalnav-v0.2/exports/`
- `out/infinigen_imports/kr_*` 정식 import
- `_external/`
- `.backup.*`, `.staging.*`
- `bridge_jobs/` 및 `bridge_jobs_archive/`
- 모든 `__authoring_map.json`, `scene_manifest.json`, `export_file_manifest.json`

## 다음 정리 작업에서 실행할 검증

삭제 전에 다음 역참조 집합을 만든다.

```text
authoring_map -> infinigen_imports/<scene>/meshes|textures
OpticalNav scenes -> authoring_map/import manifest
dataset.json -> OpticalNav scene ids
export_file_manifest.json -> export source scene/files
render_ledger.sqlite3 -> graph/render batch ids
active lock/process -> import directory
```

그 결과를 기준으로 `KEEP`, `ARCHIVE`, `DELETE` 목록을 별도 생성하고, 첫 삭제는 휴지통/이동식 archive 방식으로 수행하는 것이 안전하다. 특히 `_external`과 `__authoring_map.json`은 파일 크기가 작아 보여도 대형 mesh 자산의 연결 계약 역할을 하므로, 자산 본체보다 먼저 지우면 안 된다.

## 조사 한계

현재 실행 환경에서는 `du`가 정상적인 용량 출력을 반환하지 않아 모든 디렉터리의 재귀 용량 비교는 기록하지 못했다. 대신 디렉터리 구조, 파일 유형/개수, 파일별 표시 크기, 갱신 시각, 상태/참조 파일 및 소스 코드의 경로 참조를 기준으로 1차 분류했다. 실제 삭제 전에는 동일한 목록에 대해 재귀 용량을 다시 측정해야 한다.
