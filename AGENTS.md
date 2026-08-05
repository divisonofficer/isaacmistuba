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
│   ├── mitsuba3/                  # Device 1: WSL2 + RTX 5090용 Mitsuba/OptiX 8 소스
│   ├── mitsuba3-optix7/           # Device 2: Ubuntu + RTX 3090 ×8용 OptiX 7 호환 소스
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
├── build/mitsuba3-optix7/         # legacy/NAS artifact (런처는 사용하지 않음)
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
| **mitsuba3** | Device 1(Windows + WSL2 + RTX 5090)의 OptiX 8 계열 렌더러 소스 | `src/bsdfs/`, `src/integrators/` 등 |
| **mitsuba3-optix7** | Device 2(Ubuntu + RTX 3090 ×8)의 OptiX 7 호환 렌더러 소스. 측정 pBRDF BSDF 커스터마이즈 포함 | `src/bsdfs/measured_polarized.cpp`, `measured_polarized_rgb.cpp` |

---

## 🔭 Mitsuba 빌드 — NAS 공유 소스, 장비별 빌드 (주의!)

저장소 소스는 NAS의 `/jarvis/project/robomituba`에서 공유하지만, Mitsuba/Dr.Jit 빌드 산출물은 OS, Python ABI, NVIDIA driver, OptiX ABI와 GPU 세대에 종속된다. 따라서 아래 두 빌드는 “실험용/프로덕션용” 구분이 아니라 **서로 다른 실행 장비를 위한 호스트별 빌드**다.

| 장비 | 실행 환경 | 렌더러 소스 | 빌드·Python 경로 |
|------|-----------|-------------|------------------|
| **Device 1** | Windows + WSL2 + RTX 5090 (Blackwell, compute capability 12.0) | `modules/mitsuba3` | `/home/jinnyeong/robomituba-build/mitsuba3`, 보통 `/usr/bin/python3` |
| **Device 2** | Ubuntu server + RTX 3090 ×8 cluster | `modules/mitsuba3-optix7` | `${ROBOMITUBA_MITSUBA_BUILD_DIR:-$HOME/robomituba-build/mitsuba3-optix7}`, `/root/miniconda3/envs/mitsuba_optix7/bin/python` |

- Device 1은 OptiX 8 계열 빌드이며 WSL driver library가 필요할 때 `LD_LIBRARY_PATH=/usr/lib/wsl/lib`를 사용한다.
- Device 2는 기존 cluster driver와의 호환을 위해 OptiX 7 계열 빌드를 사용한다. 자세한 환경 제약은 `docs/2026-05-19_phase_r_environment_handoff.md`를 참고한다.
- `scripts/run_daemon_optix7.sh`와 관련 런처는 첫 GPU의 compute capability가 `12.0`이면 Device 1 빌드, 그 외에는 Device 2 빌드를 기본 선택한다. 환경변수로 덮어쓸 수 있으므로 실제 worker 경로를 로그에서 다시 확인한다.
- **NAS에서 소스 commit은 공유해도 `build/`, 가상환경, `.so`, Dr.Jit cache는 장비 사이에 복사하거나 교차 재사용하지 않는다.** 각 장비에서 자기 toolchain으로 다시 빌드한다.
- C++ BSDF/플러그인 변경을 양쪽 장비에 배포하려면 두 소스 트리의 대응 변경 여부를 확인하고, 각 장비 빌드를 별도로 재컴파일·검증한다. 한쪽의 성공은 다른 쪽 반영을 의미하지 않는다.
- 렌더 또는 플러그인 검증 기록에는 최소한 `hostname`, GPU 이름/compute capability, driver, Python 경로, `ROBOMITUBA_MITSUBA_PYTHONPATH`, Mitsuba variants와 plugin `.so` 경로를 남긴다.
- “현재 프로덕션 빌드”를 경로명만 보고 단정하지 않는다. 작업을 실행하는 장비와 daemon worker가 실제 로드한 경로가 기준이다.

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
- 주요 환경변수(런처에서 주입): `ROBOMITUBA_RENDER_GPU_INDICES`(예 `0,1,2,3`), `ROBOMITUBA_SCENE_LOAD_CONCURRENCY`, `ROBOMITUBA_MITSUBA_PYTHON`/`_PYTHONPATH`(현재 장비의 빌드 지정), `ROBOMITUBA_DISABLE_CUDA`, `ROBOMITUBA_DISABLE_CPU_FALLBACK`.

---

## 🎨 측정 재질 (HPBRDF) & Channel-Split RGB

- `data/hpbrdf_2025/` 는 분광 밴드가 많은 측정 pBRDF. 풀스펙트럼 렌더는 밴드당 ~200MB로 메모리 부담.
- 최적화: R/G/B에 해당하는 단일밴드 슬라이스(`channels/{mat}/{614,542,446}.pbrdf`)만 골라 렌더 → 한 번에 RGB 합성.
- BSDF 플러그인 `measured_polarized` (분광/편광) 와 `measured_polarized_rgb` (RGB 합성) 가 이를 담당.
- **렌더 파이프라인 분기** (`multimodal.py`): `use_channel_rgb_plugin` 이면 단일패스 `measured_polarized_rgb` 렌더, 실패 시 3-pass channel-split fallback(`_compose_channel_split_rgb`).

### ⚠️ 과거 이슈 / 현재 확인 절차

- 2026-06-15에는 Device 2 빌드에서 `measured_polarized_rgb` 로드 실패로 3-pass fallback이 실행됐고, compose(`_rgb_channel_intensity`)가 일반 재질을 gray(R=G=B)로 만드는 문제가 있었다.
- 이후 두 빌드에 플러그인 산출물이 존재한 기록이 있지만, NAS의 소스나 다른 장비의 `.so` 존재만으로 현재 worker 반영을 판단하면 안 된다.
- gray 렌더가 재발하면 재빌드부터 하지 말고 daemon log의 worker Python/PYTHONPATH, 해당 장비의 `plugins/measured_polarized_rgb.so`, `mi.variants()`와 실제 plugin load smoke를 순서대로 확인한다.
- 플러그인이 현재 장비 빌드에 없거나 stale일 때만 대응 소스 트리를 그 장비에서 재컴파일한다. Device 1 성공은 Device 2 반영을, Device 2 성공은 Device 1 반영을 보장하지 않는다.
- black frame(EXR≈0)은 이 channel-split gray 문제와 별개이므로 조명, 카메라와 scene staging을 조사한다.

---

## 🚀 Quick Start

```bash
# 모듈 (editable install)
pip install -e modules/robomituba_bridge -e modules/mitsuba_converter -e modules/navigation_dataset

# Device 1: WSL2 + RTX 5090 빌드 확인
export LD_LIBRARY_PATH=/usr/lib/wsl/lib:$LD_LIBRARY_PATH
source /home/jinnyeong/robomituba-build/mitsuba3/setpath.sh
python -c "import mitsuba as mi; print(mi.variants())"

# Device 2: Ubuntu + RTX 3090 cluster 빌드 확인
PYTHONPATH="${ROBOMITUBA_MITSUBA_BUILD_DIR:-$HOME/robomituba-build/mitsuba3-optix7}/python" \
  /root/miniconda3/envs/mitsuba_optix7/bin/python \
  -c "import mitsuba as mi; print(mi.variants())"

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

## 🔎 Agent Search Scope

대용량 렌더 출력과 외부 데이터가 소스 탐색에 섞이지 않도록 다음 규칙을 따른다.

1. 기본 소스 탐색 범위는 `apps/`, `modules/*/src/`, `modules/*/tests/`, `tools/`, `scripts/`, `configs/`, `docs/` 및 루트 설정 파일이다. WebUI는 `apps/webui/src/`를 우선한다.
2. `.ignore`에 정의된 `out/`, 외부 데이터셋, asset cache, build/cache 디렉터리와 EXR/NPZ 등 대형 바이너리는 기본 재귀 탐색에서 제외한다. `configs/datasets/`는 소스 설정이므로 제외하지 않는다.
3. 소스 탐색에는 `rg`와 `rg --files`를 사용하고 `.ignore`를 우회하는 `-uuu`, `--no-ignore`는 관련 산출물 조사가 명시적으로 필요한 경우에만 사용한다.
4. 저장소 전체 재귀 검색은 최초 위치 파악 용도로 최대 한 번만 수행한다. 파일 위치를 찾은 뒤에는 디렉터리, 확장자 또는 glob을 지정해 범위를 좁힌다.
5. 렌더 장애를 조사할 때는 `out/` 전체를 검색하지 않는다. 해당 scene/job ID를 먼저 확정하고 `out/bridge_jobs/<job>/job_status.json`, `render_progress.log`, `requests/`, `observations/`처럼 알려진 경로를 직접 읽는다.
6. 병렬/background 탐색은 서로 독립적인 범위에만 사용하며 최대 2개로 제한한다. 여러 탐색기가 동일한 저장소 전체 검색을 반복하지 않게 한다.
7. `.ignore`는 탐색 성능을 위한 규칙이며 파일 소유권이나 삭제 정책이 아니다. 무시된 파일을 수정·삭제해야 한다는 의미로 해석하지 않는다.

---

## 🐛 Troubleshooting

| 문제 | 원인 | 해결 |
|------|------|------|
| `No module mitsuba` | 현재 장비와 Python/PYTHONPATH 불일치 | worker가 선택한 Device 1/2 경로와 `ROBOMITUBA_MITSUBA_*` 확인 |
| `Could not initialize OptiX` | 장비별 driver/OptiX ABI 불일치 | Device 1은 WSL library path, Device 2는 OptiX 7 호환 build와 driver 확인 |
| 렌더가 흑백(gray)으로 나옴 | `measured_polarized_rgb` 로드 실패 → channel-split fallback | worker 경로와 현재 장비 plugin load smoke 후 필요한 빌드만 재컴파일 |
| 검은색(black) 렌더 | 조명/카메라/씬 staging 문제 | manifest/scene XML, 조명 확인 |
| 플러그인 수정이 반영 안 됨 | 다른 장비의 소스/빌드를 수정함 | daemon worker 경로를 확인하고 해당 Device 1/2 빌드를 그 장비에서 재컴파일 |
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
