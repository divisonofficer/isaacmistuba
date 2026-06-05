# Robomituba - Isaac Sim ↔ Mitsuba 3 Bridge

## 🎯 Project Overview

**로봇 시뮬레이션 데이터 생성 플랫폼**

이 프로젝트는 현재 /jarvis/project/robomituba
에 저장되어있으며, 이 이외의 경로의 의존성을 가지지 않는다.

Isaac Sim에서 로봇 장면을 작성하고, 고품질 센서 데이터(RGB, Depth, Normal, Polarization 등)를 **Mitsuba 3 렌더러**로 생성하는 통합 시스템입니다.

### Key Vision
```
Isaac Sim (물리 시뮬레이션 + 장면 저작)
    ↓
Robomituba Bridge (데이터 교환 계약)
    ↓
Mitsuba Converter (USD → 렌더링)
    ↓
High-Quality Sensor Data (multimodal output)
    ↓
ML/Vision Tasks (로봇 학습)
```

### Core Features
- 🤖 **Isaac Sim integration**: 실제같은 로봇 시뮬레이션 데이터
- 🎨 **High-quality rendering**: Mitsuba 3 (GPU 지원)
- 📸 **Multimodal output**: RGB, Depth, Normal, Polarization, etc.
- 🌉 **Bridge contract**: 독립적인 Isaac ↔ Mitsuba 통신
- 🔄 **Modular design**: 각 모듈이 독립적으로 작동
- ⚡ **Performance**: GPU 병렬화로 빠른 생성

---

## 📊 Project Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         ROBOMITUBA SYSTEM                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────────────┐  ┌──────────────────────┐             │
│  │   Isaac Sim          │  │   Blender            │             │
│  │  (USD Authoring)     │  │  (USD Authoring)     │             │
│  └──────────┬───────────┘  └──────────┬───────────┘             │
│             │                         │                          │
│             └────────────┬────────────┘                          │
│                          │                                       │
│                          ▼                                       │
│         ┌────────────────────────────────┐                      │
│         │   robomituba_bridge/           │                      │
│         │  Job Manifest + Snapshot       │                      │
│         │  (Pure Python, no deps)        │                      │
│         └────────────┬───────────────────┘                      │
│                      │                                           │
│                      │ (JSON + geometry)                         │
│                      ▼                                           │
│         ┌────────────────────────────────┐                      │
│         │   mitsuba_converter/           │                      │
│         │  USD→Mitsuba Pipeline          │                      │
│         │  + Multimodal Rendering        │                      │
│         └────────────┬───────────────────┘                      │
│                      │                                           │
│                      ▼                                           │
│         ┌────────────────────────────────┐                      │
│         │   mitsuba3/ (submodule)        │                      │
│         │  Mitsuba 3 Renderer            │                      │
│         │  (CUDA/OptiX GPU support)      │                      │
│         └────────────┬───────────────────┘                      │
│                      │                                           │
│                      ▼                                           │
│    ┌──────────────────────────────────┐                         │
│    │  High-Quality Sensor Data        │                         │
│    │  (EXR/HDR outputs)               │                         │
│    │  ├─ RGB images                   │                         │
│    │  ├─ Depth maps                   │                         │
│    │  ├─ Normal maps                  │                         │
│    │  ├─ Polarization                 │                         │
│    │  ├─ Decomposition (D/I)          │                         │
│    │  └─ Robot state                  │                         │
│    └──────────────────────────────────┘                         │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 Directory Structure

```
/jarvis/project/robomituba/
├── modules/                                 # ⭐ 핵심 모듈 (3개)
│   ├── robomituba_bridge/
│   │   ├── src/robomituba_bridge/
│   │   │   ├── types.py                    # Dataclass 정의
│   │   │   ├── manifest.py                 # Job manifest
│   │   │   ├── paths.py                    # Path handling
│   │   │   ├── io.py                       # JSON I/O
│   │   │   └── material_mapping.py
│   │   ├── tests/
│   │   └── AGENTS.md                       # 📖 자세한 가이드
│   │
│   ├── mitsuba_converter/
│   │   ├── src/mitsuba_converter/
│   │   │   ├── usd_loader.py               # USD → IR
│   │   │   ├── mitsuba_builder.py          # IR → Mitsuba dict
│   │   │   ├── multimodal.py               # 멀티모달 렌더링
│   │   │   ├── observation_bridge.py       # Observation manifest
│   │   │   ├── render_daemon.py            # HTTP 렌더링 서버
│   │   │   ├── pipeline.py                 # 통합 파이프라인
│   │   │   └── cli.py                      # CLI
│   │   ├── tests/
│   │   └── AGENTS.md                       # 📖 자세한 가이드
│   │
│   ├── mitsuba3/                          # (Git submodule)
│   │   ├── src/                           # 렌더러 핵심
│   │   ├── include/
│   │   ├── docs/
│   │   └── AGENTS.md                      # 📖 가이드
│   │
│   └── README.md
│
├── apps/                                   # 렌더링 애플리케이션
│   ├── render_candidate_cameras.py
│   ├── render_selected_cameras_multimodal.py
│   ├── render_curated_multimodal.py
│   ├── render_reflective_island_frontal_demo.py
│   ├── render_saved_request_multibranch.py
│   ├── make_selected_camera_sheets.py
│   ├── visualize_camera_floorplan.py
│   ├── isaac_capture_current_view_request.py
│   ├── run_render_daemon.py
│   └── AGENTS.md                          # 📖 렌더링 앱 가이드
│
├── scenes/                                # USD 씬 파일
│   ├── mitsuba3/                         # Mitsuba 테스트 씬
│   └── moorelane/                        # MooreLane 씬
│
├── assets/                                # 3D 모델 및 텍스처
│   ├── moorelane/
│   └── ...
│
├── out/                                   # 렌더링 결과 (bridge_jobs 포함)
│   ├── bridge_jobs/
│   │   ├── job-20260414T120000Z-abc123/
│   │   │   ├── manifest.json
│   │   │   ├── snapshot/
│   │   │   ├── usd/
│   │   │   ├── renders/
│   │   │   └── logs/
│   │   └── ...
│   └── ...
│
├── vendor_datasets/                       # 외부 데이터셋
├── vendor_docs/                           # 외부 문서
├── vendor_datasets/measured_materials/    # 측정 재질
│
├── tests/                                 # 통합 테스트
│   ├── contract/
│   ├── fixtures/
│   └── ...
│
└── AGENTS.md                              # 📖 이 파일
```

### Key Statistics
```
Module Files: 40+ Python files
- robomituba_bridge: 6 files (387 LOC)
- mitsuba_converter: 12 files (5,916 LOC)
- mitsuba3: C++ renderer (external)

Apps: 9 rendering applications
Tests: Integration test suite
```

---

## 🔄 Data Flow Examples

### Example 1: Isaac Sim → Mitsuba Rendering

```
1. Isaac Sim
   ├─ USD 씬 생성 (geometry, materials, lights)
   ├─ 카메라 배치
   └─ 내보내기 (Export to Render)

2. robomituba_bridge
   ├─ SceneSnapshot 캡처
   ├─ Geometry export (OBJ)
   ├─ Texture 복사
   └─ JobManifest 생성
   → out/bridge_jobs/job-20260414T120000Z-abc123/

3. mitsuba_converter
   ├─ load_job_bundle()
   ├─ SceneSnapshot 읽기
   ├─ UsdSceneLoader (fallback)
   ├─ MitsubaSceneBuilder
   └─ render_modalities()

4. mitsuba3
   ├─ GPU 초기화
   ├─ Scene 로드
   ├─ Path tracing
   └─ EXR 저장

5. Output
   out/bridge_jobs/job-.../renders/
   ├─ camera_0/rgb.exr
   ├─ camera_0/depth.exr
   ├─ camera_0/normal.exr
   ├─ camera_1/rgb.exr
   └─ observation_bundle.json
```

### Example 2: Backend Job Queue

```
Frontend (React/Svelte)
  ↓ RenderRequest
Backend (FastAPI)
  ├─ Create Job
  └─ QueueProcessor
  
      ↓ subprocess
  
  /jarvis/project/robomituba/apps/render_*.py
      ↓
  mitsuba_converter.pipeline
      ↓
  mitsuba3 (GPU)
      ↓
  EXR files
      ↓
  Database update
  ↓
Frontend (polling)
  ├─ GET /api/jobs/{job_id}
  └─ UI update
```

---

## 🚀 Getting Started

### Prerequisites

```bash
# System
- Python 3.10+
- NVIDIA GPU (optional, for CUDA)
- cmake (for building mitsuba3)

# Python packages
pip install mitsuba numpy pydantic pyyaml

# Git submodules
git clone <repo>
cd robomituba
git submodule update --init --recursive
```

### Quick Start

```bash
# 1. 모듈 설치
cd /jarvis/project/robomituba/modules/robomituba_bridge
pip install -e .

cd /jarvis/project/robomituba/modules/mitsuba_converter
pip install -e .

# 2. Mitsuba 설정
python -c "import mitsuba as mi; mi.set_variant('cuda_rgb'); print('Ready!')"

# 3. 렌더링 테스트
python -c "
from mitsuba_converter import convert_usd_to_mitsuba_dict
import mitsuba as mi

mi.set_variant('cuda_rgb')
scene_dict = convert_usd_to_mitsuba_dict('scenes/mitsuba3/cornell_box.usd')
scene = mi.load_dict(scene_dict)
image = mi.render(scene)
print('Success!')
"

# 4. Daemon 시작
python /jarvis/project/robomituba/apps/run_render_daemon.py
# → http://localhost:8001/render

# 5. 렌더링 요청
curl -X POST http://localhost:8001/render \
  -d '{"manifest_path": "out/bridge_jobs/.../manifest.json"}'
```

---

## 🏗️ Core Concepts

### Job Manifest (robomituba_bridge)

**정의**: 렌더링 작업의 메타데이터 + 씬 스냅샷

```
Job Manifest = {
  job_id: "job-20260414T120000Z-abc123"
  scene_id: "mitsuba3_cornell"
  frame_id: "frame_0"
  
  paths: {
    job_dir: "out/bridge_jobs/job-..."
    snapshot_dir: ".../snapshot/"
    scene_snapshot: ".../scene.json"
    usd_stage: ".../stage.usda"
    renders_dir: ".../renders/"
  }
}
```

### Scene Snapshot

**정의**: USD 씬의 스냅샷 (geometry, materials, cameras, lights)

```
SceneSnapshot = {
  scene_id: "scene_id"
  meshes: [MeshRecord, ...]           # OBJ 경로 포함
  materials: [MaterialRecord, ...]    # BSDF 파라미터
  cameras: [CameraRecord, ...]
  lights: [LightRecord, ...]
}
```

### Render Request (observation_bridge)

**정의**: 특정 카메라/모달리티 렌더링 요청

```
RenderRequest = {
  request_id: "req_001"
  job_id: "job-..."
  camera_specs: [CameraSpec, ...]     # 렌더링할 카메라
  modalities: ["rgb", "depth", ...]   # 원하는 출력
  render_settings: {spp: 64, ...}
}
```

---

## 📚 Module Documentation

각 모듈별 상세 가이드:

1. **robomituba_bridge** (`modules/robomituba_bridge/AGENTS.md`)
   - 데이터 구조 정의
   - Job manifest 생성/검증
   - Path 규칙 (repo-relative)
   - I/O 유틸리티

2. **mitsuba_converter** (`modules/mitsuba_converter/AGENTS.md`)
   - USD 로더
   - Mitsuba scene 빌더
   - 멀티모달 렌더링
   - Render daemon
   - CLI 사용법

3. **mitsuba3** (`modules/mitsuba3/AGENTS.md`)
   - Mitsuba 3 소개
   - Variant 선택
   - 성능 팁
   - GPU 사용법

4. **apps** (`apps/AGENTS.md`)
   - 9개 렌더링 앱
   - 독립 실행 및 Daemon 사용법
   - Job submission 방법

---

## 🔌 Integration Points

### Isaac Sim Plugin (Future)

```python
# Isaac에서 robomituba 사용 (미구현)
from robomituba_bridge import write_job_bundle, ensure_job_layout

snapshot = export_isaac_scene_as_snapshot()
layout = ensure_job_layout(repo_root, job_id)
write_job_bundle(repo_root, layout, snapshot, manifest)
```

### Blender Add-on (Future)

```python
# Blender에서 robomituba 사용 (미구현)
bpy.ops.robomituba.export_job(job_id="job-123")
```

### Backend API

```bash
# Render 요청
curl -X POST http://backend:8000/api/jobs \
  -d '{
    "dataset_id": 1,
    "job_type": "render",
    "config": {
      "script": "render_selected_cameras_multimodal.py",
      "manifest_path": "out/bridge_jobs/job-123/manifest.json"
    }
  }'

# 상태 조회
curl http://backend:8000/api/jobs/1
```

---

## 💾 Key File Formats

### Job Manifest (JSON)

```json
{
  "job_id": "job-20260414T120000Z-abc123",
  "scene_id": "mitsuba3_cornell",
  "frame_id": "frame_0",
  "created_at": "2026-04-14T12:00:00Z",
  "paths": {
    "job_dir": "out/bridge_jobs/job-...",
    "manifest": "out/bridge_jobs/job-.../manifest.json",
    "scene_snapshot": "out/bridge_jobs/job-.../snapshot/scene.json",
    "usd_stage": "out/bridge_jobs/job-.../usd/stage.usda",
    "renders_dir": "out/bridge_jobs/job-.../renders/"
  }
}
```

### Scene Snapshot (JSON)

```json
{
  "scene_id": "mitsuba3_cornell",
  "frame": {
    "frame_id": "frame_0",
    "time_code": 0.0,
    "meters_per_unit": 1.0,
    "up_axis": "Y"
  },
  "meshes": [
    {
      "mesh_id": "mesh_0",
      "name": "cube",
      "geometry_path": "out/bridge_jobs/.../geometry/cube.obj",
      "material_id": "mat_0",
      "transform": [...]
    }
  ],
  "materials": [...],
  "cameras": [...],
  "lights": [...]
}
```

### Render Output (EXR + JSON)

```
renders/
├── camera_0/
│  ├── rgb.exr               # 32-bit float HDR
│  ├── depth.exr             # normalized [0, 1]
│  ├── normal.exr            # [-1, 1]
│  ├── albedo.exr            # base color
│  └── ...
├── camera_1/
│  └── ...
└── observation_bundle.json  # 메타데이터
```

---

## 🧪 Testing

```bash
# Unit tests
cd modules/robomituba_bridge && pytest tests/
cd modules/mitsuba_converter && pytest tests/

# Integration test
python tests/contract/test_bridge_contract.py

# E2E test
python tests/e2e_rendering.py
```

---

## 🐛 Troubleshooting

| 문제 | 원인 | 해결 |
|------|------|------|
| "No module mitsuba" | Mitsuba 미설치 | `pip install mitsuba` |
| "variant not set" | Mitsuba variant 미설정 | `mi.set_variant('cuda_rgb')` |
| "GPU out of memory" | spp/resolution 너무 높음 | 값 감소 |
| "geometry path not found" | repo-relative 경로 잘못됨 | resolve_repo_path() 확인 |
| "Black rendering" | 조명/재질 없음 | 기본값 확인 |

---

## 🎯 Next Steps / Roadmap

### Short-term
- [ ] Isaac Sim export plugin 구현
- [ ] Blender add-on 구현
- [ ] 성능 최적화 (batch rendering)
- [ ] 추가 modality (polarization, etc.)

### Mid-term
- [ ] 분산 렌더링 (multi-machine)
- [ ] Real-time preview
- [ ] Material library 확장
- [ ] HDR 환경맵 지원

### Long-term
- [ ] Inverse rendering (역조명)
- [ ] Real-time NeRF 학습
- [ ] Physics-aware rendering
- [ ] 자동 재질 추정

---

## 📖 Documentation Index

```
/jarvis/project/robomituba/
├── AGENTS.md                          ← 이 파일 (프로젝트 개요)
├── modules/
│   ├── robomituba_bridge/AGENTS.md   ← Bridge contract 상세
│   ├── mitsuba_converter/AGENTS.md   ← 변환 및 렌더링 상세
│   └── mitsuba3/AGENTS.md            ← Mitsuba 3 렌더러 가이드
└── apps/AGENTS.md                    ← 렌더링 앱 가이드
```

---

## 👥 Contributing

```bash
# 1. Feature branch
git checkout -b feature/your-feature

# 2. Make changes
# - Update relevant AGENTS.md
# - Add tests
# - Follow code style

# 3. Commit
git commit -m "[feature] description"

# 4. Push & PR
git push origin feature/your-feature
```

---

## 📝 Key Design Decisions

### 1. Pure Python Bridge (robomituba_bridge)
- **왜?** 독립성, 이식성, 빠른 개발
- **결과**: Isaac/Mitsuba 양쪽에서 간단하게 사용 가능

### 2. Repo-relative Paths
- **왜?** 이동 가능성, 배포 용이
- **결과**: 어디서나 데이터 사용 가능

### 3. Job Manifest Pattern
- **왜?** 추적 가능성, 재현성
- **결과**: 모든 렌더링 작업이 문서화됨

### 4. Multimodal from Start
- **왜?** ML/vision tasks 지원
- **결과**: RGB 외 다양한 센서 데이터

### 5. HTTP Daemon for Rendering
- **왜?** 원격 작업, 확장성
- **결과**: 분산 렌더링 기반 구축

---

## 🔗 Related Projects

- **Mitsuba 3**: https://github.com/mitsuba-renderer/mitsuba3
- **Isaac Sim**: https://developer.nvidia.com/isaac-sim
- **NVIDIA Research**: https://research.nvidia.com/

---

## 📄 License

Robomituba는 Mitsuba 3 (GPL v3)를 사용하므로 **GPL v3** 라이선스입니다.

---

## 🎓 Learning Path

### 1️⃣ 초급 (Beginner)
- AGENTS.md (이 파일) 읽기
- 각 모듈의 Quick Start 따라하기
- 예시 렌더링 실행

### 2️⃣ 중급 (Intermediate)
- robomituba_bridge 타입 이해
- Job manifest 직접 생성
- mitsuba_converter 파이프라인 커스터마이징

### 3️⃣ 고급 (Advanced)
- Mitsuba 3 custom BSDF 추가
- 분산 렌더링 구현
- Inverse rendering

---

## 📞 Support

- 📖 **문서**: 각 AGENTS.md 파일
- 🔧 **이슈**: GitHub issues
- 💬 **토론**: GitHub discussions
- 📧 **문의**: project maintainer

---

## 🙏 Acknowledgments

- **Mitsuba 3**: EPFL RGL lab
- **Isaac Sim**: NVIDIA
- **Project contributors**: robomituba team

---

*Last Updated: 2026-04-14*
*Project: /jarvis/project/robomituba*
*Total Module Count: 3 (bridge, converter, mitsuba3)*
*Documentation: 5 AGENTS.md files*
