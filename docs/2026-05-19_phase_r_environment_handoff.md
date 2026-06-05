# Phase R 환경 핸드오프 (2026-05-19)

이 문서는 *컨테이너 내부 에이전트* 가 cold start 해서 즉시 작업하도록 만든 핸드오프 노트.
주 환경/제약/지금까지 적용된 코드 변경/현재 차단 이슈/다음 액션을 한 곳에 모음.

---

## 1. 환경

| 항목 | 값 |
|---|---|
| 호스트 GPU | NVIDIA RTX 3090 × 8 (24 GB each) |
| 호스트 NVIDIA driver | **525.89.02** (R525) |
| OptiX 8.0 요구사항 | driver R535+ — **미달** |
| 컨테이너 root path | `/jarvis/project/robomituba/` |
| 컨테이너 base Python | `/root/miniconda3/bin/python` (3.12.9) |
| 컨테이너 사용자 | root |
| GPU access | 컨테이너 안에서 GPU 0–7 모두 visible (`nvidia-smi`) |

`(base)` env 에는 **mitsuba/drjit 없음**. 옛 빌드는 호스트 `/home/jinnyeong/...` 경로라 컨테이너 안에서 보일 수도/안 보일 수도 있음 (mount 상태 확인 필요).

---

## 2. 핵심 제약

1. 호스트 driver R525 < R535 → **OptiX 8 빌드의 mitsuba 의 모든 cuda_* 변종이 런타임 init 실패**
   ```
   jit_optix_api_init(): Failed to load OptiX library!
   ```
2. 큐레이션 RGB 가 OptiX 7 호환 wheel 로는 정상 작동 확인:
   ```
   jit_optix_api_init(): loaded OptiX (via 7.4 ABI).
   ```
3. 호스트 driver 권한 없음 → 업그레이드 불가.

---

## 3. OptiX 7 호환 환경 (검증 완료)

컨테이너 안 `mitsuba_optix7` conda env. PyPI wheel.

```bash
conda create -y -n mitsuba_optix7 python=3.10
conda activate mitsuba_optix7
pip install mitsuba==3.4.1   # drjit==0.4.4 자동 dependency
pip install numpy pillow
```

| 변종 | 가용 | OptiX |
|---|---|---|
| `scalar_rgb` | ✓ | — |
| `scalar_spectral` | ✓ | — |
| `cuda_ad_rgb` | ✓ | 7.4 ABI 작동 ✓ |
| `llvm_ad_rgb` | ✓ | — (CPU) |
| `cuda_ad_spectral` | ✗ wheel 에 없음 | |
| `cuda_ad_spectral_polarized` | ✗ wheel 에 없음 | |

검증 명령:
```bash
/root/miniconda3/envs/mitsuba_optix7/bin/python -c "
import mitsuba as mi
mi.set_variant('cuda_ad_rgb')
scene = mi.load_dict({'type':'scene','integrator':{'type':'path'},
    'sensor':{'type':'perspective','film':{'type':'hdrfilm','width':16,'height':16}},
    'shape':{'type':'sphere'}})
mi.render(scene); print('cuda_ad_rgb OK')
"
```

---

## 4. Phase R 코드 변경 요약

### Daemon (Python 3.12 base env 에서 띄움 — mitsuba 안 import)

| 파일 | 변경 |
|---|---|
| [apps/run_render_daemon.py](apps/run_render_daemon.py) | `_bootstrap_project_sys_path()` 자동 추가, `_check_runtime()` 가 INPROCESS=0 일 때 skip |
| [modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py](modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py) | `_RENDER_INPROCESS` env, `WorkerManager` 인스턴스, listener `_on_render_worker_event` + `_handle_render_job_event`, R-3 preview path 분기, R-4 full /render path 분기 + `_submit_render_job_to_worker` |

### Worker (Python 3.10 wheel env 에서 spawn)

| 파일 | 역할 |
|---|---|
| [modules/mitsuba_converter/src/mitsuba_converter/preview_worker.py](modules/mitsuba_converter/src/mitsuba_converter/preview_worker.py) | JSONL stdin/stdout. dispatch 4종 (curated_preview / measured_preview / channel_split_preview / render_job). `_DispatchHeartbeat`, `_set_render_log_level` |
| [modules/mitsuba_converter/src/mitsuba_converter/worker_manager.py](modules/mitsuba_converter/src/mitsuba_converter/worker_manager.py) | spawn / heartbeat / drjit critical kill, env 분기 (PYTHON, PYTHONPATH, GPU_INDICES), project src 자동 PYTHONPATH |

### Sphere preview / OBJ export

| 파일 | 변경 |
|---|---|
| [modules/mitsuba_converter/src/mitsuba_converter/multimodal.py](modules/mitsuba_converter/src/mitsuba_converter/multimodal.py) | staged scene XML write 직전 texture filename rewrite. `ROBOMITUBA_TEXTURE_MAX_RESOLUTION` 이 `>0` 이면 PNG/JPG/TIFF/BMP 및 EXR envmap 을 downsample cache 로 교체 |
| [modules/mitsuba_converter/src/mitsuba_converter/sphere_preview.py](modules/mitsuba_converter/src/mitsuba_converter/sphere_preview.py) | B-1: `_KEEP_KERNEL_CACHE` env, `_release_gpu_pool` 에 `flush_kernel_cache` skip |
| [modules/mitsuba_converter/src/mitsuba_converter/mitsuba_runtime.py](modules/mitsuba_converter/src/mitsuba_converter/mitsuba_runtime.py) | `ENV_DISABLE_CPU_FALLBACK` 추가 (resolve_variant 에서 `allow_cpu` 강제 False) |
| [modules/mitsuba_converter/src/mitsuba_converter/usd_export_obj_mtl.py](modules/mitsuba_converter/src/mitsuba_converter/usd_export_obj_mtl.py) | `_sanitize_normals` (zero/NaN/inf → +Y), `export_roots_to_obj_mtl(stage=...)` 인자 추가 |

### Scripts

| 파일 | 역할 |
|---|---|
| [scripts/reexport_moorelane_objs.py](scripts/reexport_moorelane_objs.py) | moorelane 의 207 material 재 export. 이미 1회 실행 — `out/moorelane_full_export/objs/` 가 sanitize 적용된 새 export. 옛 데이터는 `objs.broken/` |

Data repair note:
- `out/moorelane_full_export/objs/_NO_MATERIAL.obj` 가 sanitize swap 과정에서 누락되어 Mitsuba load 가 실패했음.
- `objs.broken/_NO_MATERIAL.obj` 에서 복구하고 zero/NaN/inf normal sanitize 적용 완료.

---

## 5. 운영 환경 변수

| Env | 기본값 | 의미 |
|---|---|---|
| `ROBOMITUBA_RENDER_INPROCESS` | `0` | 기본은 worker subprocess 격리. `1` 이면 legacy in-process 렌더링 |
| `ROBOMITUBA_MITSUBA_PYTHON` | (unset) | worker 가 사용할 Python 인터프리터 절대경로 |
| `ROBOMITUBA_MITSUBA_PYTHONPATH` | (unset) | worker PYTHONPATH 에 prepend 할 디렉토리 |
| `ROBOMITUBA_RENDER_GPU_INDICES` | `0` | worker 들이 attach 할 host GPU index (single int 또는 `"1,2,3"`) |
| `ROBOMITUBA_KEEP_KERNEL_CACHE` | `1` | OptiX kernel cache 유지 (두 번째 호출 ~1초) |
| `ROBOMITUBA_DISABLE_CUDA` | (unset) | 모든 cuda 변종 무시 (전 dispatch 종류) |
| `ROBOMITUBA_FULL_RENDER_DISABLE_CUDA` | (unset) | **풀 `/render` 잡만** cuda 변종 disable (CPU 강제). 큐레이션 RGB 프리뷰는 그대로 GPU 사용. GPU OOM 우회용. preview_worker 의 dispatch 시작 시 토글 적용. |
| `ROBOMITUBA_TEXTURE_MAX_RESOLUTION` | `0` | `>0` 이면 staged scene XML 의 bitmap/envmap 텍스처를 downsample cache 파일로 rewrite. `scripts/run_daemon_optix7.sh` 는 기본 `2048`. |
| `ROBOMITUBA_TEXTURE_CACHE_DIR` | `out/texture_cache/mitsuba_downsampled` | downsample 된 텍스처 캐시 위치 |
| `ROBOMITUBA_DISABLE_CPU_FALLBACK` | (unset) | CUDA 실패 시 LLVM 으로 fallback 안 하고 명시적 실패 |
| `ROBOMITUBA_RENDER_LOG_LEVEL` | `info` | mitsuba/drjit log level (off/error/warn/info/debug/trace) |
| `ROBOMITUBA_RENDER_HEARTBEAT_INTERVAL_S` | `5.0` | dispatch stage heartbeat 간격 |
| `ROBOMITUBA_WORKER_HEARTBEAT_TIMEOUT_S` | `30.0` (`scripts/run_daemon_optix7.sh` 는 `600`) | worker stdout heartbeat/progress 가 이 시간 동안 없으면 watchdog restart. full scene CPU render 는 `mi.render()` 내부에서 30초 이상 조용할 수 있어 launch script 는 10분으로 설정 |

Worker env dependency note:
```bash
/root/miniconda3/envs/mitsuba_optix7/bin/python -m pip install imageio
```
`imageio` 는 EXR envmap downsample 에 필요. PNG/JPG 는 Pillow 만으로 동작.

---

## 6. 일하는 daemon launch 명령 (검증 완료)

```bash
pkill -9 -f preview_worker 2>/dev/null; pkill -f run_render_daemon.py 2>/dev/null; sleep 1

ROBOMITUBA_RENDER_GPU_INDICES=2 \
setsid -f scripts/run_daemon_optix7.sh --host 0.0.0.0 --port 8765 > /tmp/daemon.log 2>&1

# 5초 대기, 그 다음 큐레이션 1건으로 워커 spawn 강제
sleep 5
curl -X POST -s http://localhost:8765/api/material-preview/curated/aluminum/invalidate -d '{}' > /dev/null
curl -s -o /tmp/preview_check.png http://localhost:8765/api/material-preview/curated/aluminum?object=sphere
sleep 15

grep -E "worker: spawn|worker: ready|preview_bench" /tmp/daemon.log | tail
```

기대 로그:
```
[daemon] worker: spawn python=/root/.../mitsuba_optix7/bin/python ... gpu_index=2 [alt-build]
[daemon] worker: ready pid=... gpu_index=2
[worker] log_level=info heartbeat_interval=5.0s
[worker] jit_optix_api_init(): loaded OptiX (via 7.4 ABI).
[daemon] preview_bench: ... variant=cuda_ad_rgb ... total=1000~7000 ms
```

---

## 7. 현재 차단 이슈 — GPU OOM

### 증상
풀 `/render` (isaac/capture) 잡이 워커에서 dispatch 직후 죽음:
```
[daemon] render_queue: enqueue (subprocess) job_id=isaac-session-... variant=auto
Critical Dr.Jit compiler failure: cuda_check(): API error 0002 (CUDA_ERROR_OUT_OF_MEMORY): "out of memory" in /project/ext/drjit-core/src/cuda_tex.cpp:149.
[daemon] worker: exit pid=... rc=-6 recent_exits=1/3
[daemon] worker: cooldown 30s before respawn gpu_index=...
isaac-session-... failed - worker_exited: ... rc=-6 (stdout EOF — likely drjit critical / CUDA OOM)
```

### 분석
- GPU 2 는 OOM 시점 **거의 비어있음** (`nvidia-smi: 0 MiB / 24576 MiB`)
- `cuda_tex.cpp:149` = drjit 의 *texture upload* 단계
- moorelane scene 의 texture 디스크 합계 **5.6 GB / 2301 파일** ([moorelane texture audit](#moorelane-texture-audit))
- 그러나 **decoded 메모리**: 8K PNG ≈ 1 GB RGBA32f / 장, 4K ≈ 256 MB / 장, 8K HDR ≈ 동일
- 디스크 top 15 중 12 장이 4K+ → decoded 합계 24 GB+ 가능 → drjit 가 일괄 upload 시 OOM

### Framework 측면 영향
이전 CUDA full render 는 OOM 으로 실패했지만, R-4 subprocess/listener 는 정상 동작:
- robust kill (`rc=-6` 잡음)
- listener 가 `failed (worker_exited)` 로 finalise
- cooldown 후 manager 자동 respawn

현재 운영 모드는 full `/render` 에서 CUDA 를 끄고(`ROBOMITUBA_FULL_RENDER_DISABLE_CUDA=1`), texture cap 을 적용해 우회한다.

---

## 8. moorelane texture audit (참고)

```
total: 5.6 GB (디스크), 2301 files
top: LargeCloudMap.png 193 MB, ground_COLOR_8K.png 127 MB, HDRI 8K 100 MB,
     ombreRug 83 MB, walnut_8K 40 MB, 등 8K/4K 다수
```

decoded RGBA32f estimate (over-approximation; mitsuba 가 압축 형식 캐싱하면 절반):
- 8K PNG/HDR ≈ 1 GB / 장 × 12 장 = 12 GB
- 4K PNG ≈ 256 MB / 장 × 50+ 장 = 12+ GB
- **합계 24 GB 초과 가능**

---

## 9. 다음 액션 후보

| 옵션 | 효과 | 비용 | 적합성 |
|---|---|---|---|
| **A. Scene texture pre-downsample** | 8K → 2K (16× 메모리 절약) → GPU texture OOM 완화 | `ROBOMITUBA_TEXTURE_MAX_RESOLUTION=2048` 로 staged XML rewrite. 최신 scene dry-run: `rewritten=165 skipped=0`, cache 133 files / ~468 MB, EXR envmap 포함 | ★ 즉시 |
| **B. Mitsuba `<texture>` max_resolution 옵션** | 내장 옵션이면 가장 깔끔 | 확인 결과 bitmap plugin 에 `max_resolution` 없음. 대신 `format=fp16` 은 Mitsuba 3.7.1 에 있으나 wheel 3.4.1 에서는 unreferenced property | 제외 |
| **C. `ROBOMITUBA_DISABLE_CUDA=1`** | 모든 cuda 변종 disable → LLVM 만 → 시스템 RAM 사용. 시간 큼 (16분+) | env 한 줄. 영구 환경 결정 | 즉시 — 결과는 느림 |
| **D. Scene 다이어트 (LOD / 일부 mesh 제외)** | 텍스처 적은 sub-scene 만 | 적용 어려움 (사용자 의도와 충돌) | 한정적 |
| **E. B-build-B (source build v3.4.1 with spectral/polarized)** | spectral GPU 변종 추가. 단 GPU OOM 자체는 해결 안 됨 (오히려 더 큰 변종이라 더 빨리 OOM) | mitsuba 컨테이너 안 빌드 1-2 시간 + 디스크 ~10 GB | spectral 이 우선이라면 |

### 추천 우선순위

1. **A 먼저** — texture 다운샘플로 GPU 24 GB 안에 맞춤. 그러면 RGB pass 가 OptiX 7 GPU 작동.
2. 그 후 **B-build-B** — spectral / polarized cuda 변종 빌드. 풀 spectrum 도 GPU.
3. **C 는 fallback** — 시간 들지만 항상 결과 나옴.

---

## 10. 빠른 진단 명령들

```bash
# 1. daemon / worker process 상태
pgrep -af "run_render_daemon|preview_worker"

# 2. GPU 현재 상태
nvidia-smi --query-gpu=index,memory.used,memory.free,memory.total --format=csv,noheader
nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_memory --format=csv,noheader

# 3. daemon 로그 핵심 라인
grep -E "worker:|render_queue|preview_queue|preview_bench|_mark_|cuda_check|drjit|Traceback" /tmp/daemon.log | tail -50

# 4. render-jobs / material-jobs 상태
curl -s http://localhost:8765/api/render-jobs    | python3 -m json.tool | head -40
curl -s http://localhost:8765/api/material-jobs  | python3 -m json.tool | head -40

# 5. wheel 변종 다시 확인
/root/miniconda3/envs/mitsuba_optix7/bin/python -c "
import mitsuba as mi; print('variants:', mi.variants())
mi.set_variant('cuda_ad_rgb')
scene = mi.load_dict({'type':'scene','integrator':{'type':'path'},
    'sensor':{'type':'perspective','film':{'type':'hdrfilm','width':16,'height':16}},
    'shape':{'type':'sphere'}})
mi.render(scene); print('cuda_ad_rgb OK')
"
```

---

## 11. R-3/R-4 검증 결과 요약

| 시나리오 | 결과 |
|---|---|
| 큐레이션 RGB 프리뷰 (subprocess + wheel) | ✓ cuda_ad_rgb OptiX 7 GPU, 첫 호출 ~7s, 두 번째 ~1s |
| 워커 framework (spawn / ready / heartbeat / kill / respawn) | ✓ 모든 lifecycle 정상 |
| 풀 /render 잡 (subprocess + wheel) | ✓ texture cap 2048 + full-render CUDA-off + CPU SPP cap 256 으로 성공. 검증 job: `isaac-session-20260519T032842Z-retrywatch`, total ~230.6s, rgb/depth outputs + manifest 작성 |
| OBJ export sanitize | ✓ 207/207 material 재export, 21 sanitize 적용, swap 완료 |
| `_NO_MATERIAL.obj` 누락 복구 | ✓ `objs.broken/_NO_MATERIAL.obj` 에서 복구 + 438 zero normals sanitize → bad normals 0 |
| daemon HTTP 응답성 | ✓ 풀 render 가 워커에서 도는 동안 daemon 응답 보존 |

---

## 12. 미해결 의문

1. **decoded texture 의 정확한 메모리 footprint** — drjit/mitsuba 가 어떤 형식으로 GPU 에 올리는지 (RGBA8 vs RGBA32f, compressed vs uncompressed). 사실확인 필요.
2. ~~**mitsuba 의 `<texture>` 노드에서 max_resolution / mip 옵션 존재 여부**~~ — 확인 완료: `max_resolution` 없음. bitmap 파라미터는 filename/bitmap/data/filter_type/wrap_mode/format/raw/to_uv 계열.
3. ~~**현 mitsuba_builder.py 의 XML 출력이 max_resolution 을 쓸 수 있는지**~~ — 내장 옵션 부재로 제외. `multimodal._write_scene()` 단계에서 filename rewrite 방식으로 구현.
4. **부분 scene loading** — mitsuba 가 *lazy texture load* 지원하는지 (참조될 때만 load).

---

*Generated: 2026-05-19 (UTC)*
*Author: Phase R 작업 세션 (Claude Code)*
*다음 에이전트: 위 다음 액션 표 + 미해결 의문 1-4 부터 시작 추천*
