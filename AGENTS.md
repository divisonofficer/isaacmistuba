# Robomituba — Isaac/Blender ↔ Mitsuba 3 Rendering & OpticalNav Dataset Platform

> 이 프로젝트는 `/jarvis/project/robomituba` 에 저장되어 있으며, 이 경로 밖의 의존성을 가지지 않는다.
> (예외: Mitsuba 런타임 빌드는 빌드 디렉토리에 위치 — 아래 "Mitsuba 빌드" 참고.)

## 🎯 What This Project Is

USD 장면(Isaac Sim / Blender / 자체 에디터)으로부터 **Mitsuba 3 (CUDA/OptiX)** 로 고품질 멀티모달 센서 데이터(RGB, Depth, Normal, Polarization, 측정 pBRDF 등)를 생성하는 플랫폼.

초기에는 "Isaac ↔ Mitsuba bridge" 단일 목적이었으나, 현재의 주력 워크로드는 **OpticalNav 데이터셋 생성**이다: 실내 장면의 grid viewpoint × heading 스윕을 렌더링하고, viewpoint graph / traversability grid / navigation episode 와 묶어 학습용 내비게이션 데이터셋으로 export 한다.

```
씬 저작 (Isaac Sim / Blender / OpticalNav 에디터 webui)
   ↓  USD / scene XML
navigation_dataset (viewpoint graph · grid · episode · planner)
   ↓  RenderRequest
robomituba_bridge (job manifest / snapshot 계약)
   ↓
mitsuba_converter (USD→Mitsuba, 멀티모달 렌더, render daemon)
   ↓
mitsuba3 / mitsuba3-optix7 (GPU 렌더러, 측정 pBRDF BSDF 포함)
   ↓
멀티모달 출력 (EXR/PNG/NPZ) + observation manifest
   ↓
export_optical_nav_dataset.py → 학습용 번들 (images + index.jsonl + graph/grid/episodes)
```

---

## 📁 Directory Structure (현재 실제)

```
/jarvis/project/robomituba/
├── modules/                       # 5개 모듈
│   ├── robomituba_bridge/         # Job manifest / snapshot 계약 (pure Python)
│   ├── mitsuba_converter/         # USD→Mitsuba 변환 + 멀티모달 렌더 + render daemon
│   ├── navigation_dataset/        # ⭐ OpticalNav: episode/grid/graph/planner/exporter/evaluator
│   ├── mitsuba3/                  # Mitsuba 3 (submodule) — 표준 빌드 트리
│   ├── mitsuba3-optix7/           # ⭐ Mitsuba 3 OptiX7 변형 — 프로덕션 렌더러 소스
│   └── README.md
│
├── apps/                          # ⭐ 16 일반 도구 (루트) + 4 서브폴더 (특화)
│   ├── opticalnav.py              # navigation_dataset.cli 엔트리포인트
│   ├── run_render_daemon.py       # HTTP 렌더 데몬
│   ├── run_control_plane_dev.sh   # ⭐ 데몬 + webui 통합 개발 런처
│   ├── run_control_backend_dev.sh
│   ├── render_saved_request_multibranch.py  # 단일 RenderRequest 렌더 (ambient/active/polar)
│   ├── export_optical_nav_dataset.py        # ⭐ 학습용 압축 export (EXR/NPZ 제외, JPEG+graph)
│   ├── export_scene_to_usd.py     # authoring map → USD export
│   ├── bake_*.py                  # material / asset thumbnail baking
│   ├── audit_placeable_asset_texture_brdf.py / validate_material_previews.py
│   ├── auto_link_opticalnav_assets.py / asset_coverage.py / download_dtc_subset.py
│   ├── import_infinigen_scene.py  # generic Infinigen → OpticalNav importer
│   ├── visualize_camera_floorplan.py
│   ├── isaac/                     # Isaac Sim 인터랙션 (capture, script editor shim)
│   ├── scenes/                    # ⭐ scene-specific install / import (cglab / shared_office / moorelane_kitchen)
│   ├── migrations/                # one-shot fix / migration (Phase 1 metadata, channel-split grid rerender)
│   ├── legacy/                    # 옛 카메라 sweep 워크플로 (OpticalNav 데몬으로 대체됨)
│   ├── webui/                     # SvelteKit + Three.js 프론트엔드 (OpticalNav 에디터)
│   ├── isaac_extension/           # Isaac Sim 확장 (UI 패널)
│   └── isaac_standalone/          # Isaac 독립 실행 export 스크립트
│
├── data/                          # 측정 재질 데이터셋
│   ├── hpbrdf_2025/channels/{material}/{446|542|614|854}.pbrdf   # 단일밴드 채널 슬라이스
│   └── pbrdf_2020/                # KAIST pBRDF (Baek 2020)
│
├── out/
│   ├── bridge_jobs/               # 렌더 job (job당 1 frame): opticalnav-<scene>-template-vp_XXX-h_YYY-rgb
│   └── opticalnav/                # OpticalNav 데이터셋 루트
│       ├── opticalnav-v0.2/       # scenes/ episodes/ observations/ splits/ evaluation/
│       │                          # render_batches/ graph_render_batches/ exports/ thumbnails/ docs/
│       └── asset_library/
│
├── scenes/        assets/        configs/datasets/      # 씬·에셋·데이터셋 설정
├── tests/         scripts/       tools/    third_party/
├── dev_report/    docs/   notes/   related_works/       # 보고서·문서
├── vendor_datasets/   vendor_docs/
├── build/mitsuba3-optix7/         # ⭐ 프로덕션 Mitsuba 빌드 산출물 (data/, plugins/, python/)
├── AGENTS.md  CLAUDE.md           # 이 파일 (둘은 동일 미러)
└── 각 모듈/앱 디렉토리의 CLAUDE.md  # 상세 가이드
```

---

## 🧩 Modules (5)

| 모듈 | 역할 | 핵심 파일 |
|------|------|-----------|
| **robomituba_bridge** | Job manifest / SceneSnapshot / RenderRequest 데이터 계약 (의존성 없는 pure Python) | `types.py`, `manifest.py`, `paths.py`, `io.py`, `material_mapping.py` |
| **mitsuba_converter** | USD→IR→Mitsuba dict, 멀티모달 렌더, observation manifest, HTTP render daemon | `usd_loader.py`, `mitsuba_builder.py`, `multimodal.py`(대형), `observation_bridge.py`, `render_daemon.py`, `pipeline.py`, `cli.py`, `mitsuba_runtime.py` |
| **navigation_dataset** | OpticalNav 저작: episode schema, scene annotation, traversability grid, A* planner, instruction template, rollout, exporter, evaluator | `episode_schema.py`, `scene_annotations.py`, `planner.py`, `renderer.py`, `authoring_compile.py`, `cli.py` |
| **mitsuba3** | Mitsuba 3 표준 submodule. 표준 빌드 트리에서 사용 | `src/bsdfs/`, `src/integrators/` 등 |
| **mitsuba3-optix7** | ⭐ **프로덕션 렌더러 소스** (OptiX7 변형). 측정 pBRDF BSDF 커스터마이즈 포함 | `src/bsdfs/measured_polarized.cpp`, `measured_polarized_rgb.cpp` |

---

## 🔭 Mitsuba 빌드 — 두 개가 공존 (주의!)

이 저장소에는 **두 개의 Mitsuba 소스/빌드**가 있고, 어느 것이 런타임에 쓰이는지 반드시 구분해야 한다.

| 소스 | 빌드 위치 | 사용처 |
|------|-----------|--------|
| `modules/mitsuba3` | `/home/jinnyeong/robomituba-build/mitsuba3` | 실험·검증용. `setpath.sh` + `LD_LIBRARY_PATH=/usr/lib/wsl/lib` 로 로드 |
| `modules/mitsuba3-optix7` | `build/mitsuba3-optix7` | ⭐ **프로덕션 데몬/control-plane** (conda env `mitsuba_optix7`, `ROBOMITUBA_MITSUBA_PYTHONPATH=build/mitsuba3-optix7/python`) |

- 플랫폼: WSL2 + RTX GPU. OptiX 드라이버는 `/usr/lib/wsl/lib/libnvoptix.so.1`.
- 컴파일된 variant(표준 빌드 기준): `scalar_rgb, cuda_rgb, cuda_spectral, cuda_ad_spectral, cuda_ad_spectral_polarized`.
- **BSDF/플러그인을 고치면 두 트리 중 "프로덕션에서 쓰는 빌드"를 재컴파일했는지 확인할 것.** `modules/mitsuba3` 만 고치면 데몬에는 반영되지 않는다.

---

## 🗺️ OpticalNav 데이터셋 워크플로

1. **저작/컴파일** — `apps/opticalnav.py` (→ `navigation_dataset.cli`) 또는 webui 에디터로 장면 annotation·traversability grid·viewpoint graph·episode 생성. 결과는 `out/opticalnav/opticalnav-v0.2/` 아래.
2. **렌더** — grid의 각 viewpoint × heading 마다 RenderRequest 생성 → render daemon이 멀티모달 렌더 → `out/bridge_jobs/opticalnav-<scene>-template-vp_XXX-h_YYY-rgb/` 에 job 단위로 저장.
3. **Export** — `apps/export_optical_nav_dataset.py` 로 학습용 번들 생성: EXR/NPZ 제외, PNG→JPEG, `index.jsonl`(pose/intrinsics 라벨) + viewpoint graph + grid + episodes 동봉.

### bridge_jobs 레이아웃 (job = 1 frame)

```
out/bridge_jobs/opticalnav-shared_office_floor_001-template-vp_000083-h_090-rgb/
├── job_status.json
├── requests/<frame_id>.json                       # 저장된 RenderRequest (재렌더 입력)
└── observations/<frame_id>/
    ├── manifest.json                              # camera_to_world, base_pose, intrinsics, timing
    └── cameras/<camera_id>/
        ├── rgb.exr   # HDR linear float
        ├── rgb.png   # 8-bit sRGB tonemapped
        └── rgb_raw.npz  # float32 raw (EXR와 사실상 중복)
```

> 현재 scene: `glass_corridor_001/002`, `office_lobby_001`, `cornell_box_001`, `moorelane_kitchen_001`, `shared_office_floor_001`. job 총 2400+개.

---

## 🖥️ Control Plane / Render Daemon

- **`apps/run_control_plane_dev.sh`** — render daemon + webui 를 함께 띄우는 개발 런처. daemon 기본 `127.0.0.1:8765`.
- **render daemon** (`mitsuba_converter/render_daemon.py`) — RenderRequest 큐, 멀티 GPU 워커(서브프로세스 분리), scene cache.
- **webui** (`apps/webui`, SvelteKit + Three.js) — OpticalNav 장면/그래프 에디터, 렌더 모니터, XML-native preview.
- 주요 환경변수(런처에서 주입): `ROBOMITUBA_RENDER_GPU_INDICES`(예 `0,1,2,3`), `ROBOMITUBA_SCENE_LOAD_CONCURRENCY`, `ROBOMITUBA_MITSUBA_PYTHON`/`_PYTHONPATH`(프로덕션 optix7 빌드 지정), `ROBOMITUBA_DISABLE_CUDA`, `ROBOMITUBA_DISABLE_CPU_FALLBACK`.

---

## 🎨 측정 재질 (HPBRDF) & Channel-Split RGB

- `data/hpbrdf_2025/` 는 분광 밴드가 많은 측정 pBRDF. 풀스펙트럼 렌더는 밴드당 ~200MB로 메모리 부담.
- 최적화: R/G/B에 해당하는 단일밴드 슬라이스(`channels/{mat}/{614,542,446}.pbrdf`)만 골라 렌더 → 한 번에 RGB 합성.
- BSDF 플러그인 `measured_polarized` (분광/편광) 와 `measured_polarized_rgb` (RGB 합성) 가 이를 담당.
- **렌더 파이프라인 분기** (`multimodal.py`): `use_channel_rgb_plugin` 이면 단일패스 `measured_polarized_rgb` 렌더, 실패 시 3-pass channel-split fallback(`_compose_channel_split_rgb`).

### ⚠️ 알려진 이슈 / Action item (2026-06-15 기준)

- **3-pass fallback의 compose(`_rgb_channel_intensity`)가 각 파장 패스를 luminance로 붕괴**시켜, 측정 재질이 아닌 일반 재질이 **gray(R=G=B)** 로 죽는다. 결과적으로 OpticalNav grid 데이터셋(shared_office_floor 등)이 사실상 흑백 + 일부 컬러 오브젝트로 렌더됨.
- 근본 원인: 프로덕션 빌드 `build/mitsuba3-optix7` 에 **`measured_polarized_rgb.so` 가 컴파일되어 있지 않아** 플러그인 로드 실패 → 매 프레임 fallback.
- 상태:
  - `modules/mitsuba3-optix7/src/bsdfs/measured_polarized_rgb.cpp` 는 존재·등록되어 있으나 **빌드 안 됨** (RGB-only 설계 → cuda_ad_spectral 패스에서 로드 가능한지 검증 필요).
  - `modules/mitsuba3` 에 rgb+spectral+polarized 모두 지원하는 별도 구현이 추가되어 `/home/jinnyeong/robomituba-build/mitsuba3` 에서 end-to-end 컬러 복원이 검증됨 — 단, **이건 프로덕션 빌드가 아님**.
- **할 일**: 프로덕션(optix7) 빌드에 cuda_ad_spectral 에서 로드 가능한 `measured_polarized_rgb` 를 컴파일 → 전체 grid 재렌더(`apps/migrations/rerender_optical_nav_grid.py`, `--only-gray` 는 부분만 잡으니 전체 권장). black 프레임(EXR≈0)은 별도 원인.

---

## 🚀 Quick Start

```bash
# 모듈 (editable install)
pip install -e modules/robomituba_bridge -e modules/mitsuba_converter -e modules/navigation_dataset

# Mitsuba 런타임 (검증용 표준 빌드)
export LD_LIBRARY_PATH=/usr/lib/wsl/lib:$LD_LIBRARY_PATH
source /home/jinnyeong/robomituba-build/mitsuba3/setpath.sh
python -c "import mitsuba as mi; print(mi.variants())"

# OpticalNav CLI
python apps/opticalnav.py --help

# 단일 RenderRequest 렌더
python apps/render_saved_request_multibranch.py \
  out/bridge_jobs/<job>/requests/<frame>.json --variant cuda_ad_spectral

# control plane (데몬 + webui)
bash apps/run_control_plane_dev.sh

# 학습용 export
python apps/export_optical_nav_dataset.py \
  --scene shared_office_floor_001 \
  --out out/exports/shared_office_floor_001_trainable \
  --image-format jpeg --jpeg-quality 95 --zip
```

---

## 🧪 Testing

```bash
cd modules/robomituba_bridge   && pytest tests/
cd modules/mitsuba_converter   && pytest tests/
cd modules/navigation_dataset  && pytest tests/   # viewpoint_graph, authoring_map, episode 등
```

---

## 🐛 Troubleshooting

| 문제 | 원인 | 해결 |
|------|------|------|
| `No module mitsuba` | 런타임 미로드 | `setpath.sh` + `LD_LIBRARY_PATH=/usr/lib/wsl/lib` |
| `Could not initialize OptiX` | WSL OptiX 미연결 | `LD_LIBRARY_PATH` 에 `/usr/lib/wsl/lib` 추가 |
| 렌더가 흑백(gray)으로 나옴 | `measured_polarized_rgb` 미빌드 → channel-split fallback | 위 "알려진 이슈" 참고 (프로덕션 빌드에 플러그인 컴파일 + 재렌더) |
| 검은색(black) 렌더 | 조명/카메라/씬 staging 문제 | manifest/scene XML, 조명 확인 |
| 플러그인 수정이 반영 안 됨 | 잘못된 빌드 트리 컴파일 | 프로덕션은 `build/mitsuba3-optix7` 임을 확인 |
| GPU OOM | spp/resolution 과다 | 값 감소, `ROBOMITUBA_TEXTURE_MAX_RESOLUTION` 조정 |

---

## 📝 Key Design Decisions

1. **Pure Python bridge** (`robomituba_bridge`) — 의존성 없이 Isaac/Mitsuba 양쪽에서 사용.
2. **Repo-relative paths** — 이동/배포 용이. `resolve_repo_path()` 로 해석.
3. **Job manifest + observation manifest** — 모든 렌더가 재현 가능하게 문서화 (RenderRequest 저장 → 재렌더 가능).
4. **Multimodal from start** — RGB 외 depth/normal/polarization/측정 pBRDF.
5. **Render daemon + 멀티 GPU 워커** — 큐 기반, 서브프로세스 분리, scene cache.
6. **OpticalNav 데이터셋 레이어 분리** (`navigation_dataset`) — 렌더와 독립적으로 graph/grid/episode 저작.

---

## 📖 상세 문서

- `modules/robomituba_bridge/CLAUDE.md` — bridge 계약
- `modules/mitsuba_converter/CLAUDE.md` — 변환/렌더/daemon
- `modules/mitsuba3/CLAUDE.md` — Mitsuba 렌더러 가이드
- `apps/CLAUDE.md` — 렌더 앱
- `modules/navigation_dataset/README.md` — OpticalNav 저작 레이어
- `dev_report/` — 주차별 개발 보고서

---

## 📄 License

Mitsuba 3 (GPL v3) 사용 → 본 프로젝트도 **GPL v3**.

---

*Last Updated: 2026-06-15*
*Modules: 5 (robomituba_bridge, mitsuba_converter, navigation_dataset, mitsuba3, mitsuba3-optix7)*
*주력 워크로드: OpticalNav 데이터셋 생성 · 멀티모달 렌더 · 측정 pBRDF*
