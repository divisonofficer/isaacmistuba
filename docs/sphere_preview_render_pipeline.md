# Sphere Preview 렌더 파이프라인 — CPU/GPU/I/O 부하 분석

`/api/material-preview/measured/...` 한 번 요청에서 PNG 가 디스크에 쓰일 때까지 어디서 무엇이 일어나는지. 부하 진단용.

소스 위치:
- `modules/mitsuba_converter/src/mitsuba_converter/sphere_preview.py`
- `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`

---

## 전체 흐름 (one-page diagram)

```
┌─────────────┐  HTTP   ┌──────────────────────────────────────────────────┐
│  브라우저    │ ──────▶ │ render_daemon (HTTP handler)                       │
│  /api/...   │         │  - 캐시 PNG hit?  ─────▶ 즉시 200 응답 (PNG bytes) │
└─────────────┘         │  - miss: BG thread spawn + material_job 등록      │
                        └────────────────────────┬─────────────────────────┘
                                                 │ 202 Accepted (job 진행 중)
                                                 ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │ BG thread (한 번에 1개만 — _mitsuba_render_lock RLock)          │
   │                                                                  │
   │  1. variant set        (CPU, 1회 JIT init: 1~3s, 캐시 후 ~0ms)  │
   │  2. _build_scene_dict  (CPU, ms 단위, Python dict)              │
   │  3. mi.load_dict       (CPU + I/O + GPU upload)                 │
   │  4. for chunk in N:                                              │
   │       mi.render        ← GPU kernel (path tracing)              │
   │       np.array(out)    ← GPU→CPU sync barrier + float32        │
   │       running mean     ← CPU numpy                               │
   │  5. tone-map + gamma   (CPU numpy)                               │
   │  6. PIL Lanczos resize (CPU)                                     │
   │  7. PIL save PNG       (디스크 write)                            │
   │  8. _release_gpu_pool  (gc + Dr.Jit flush_malloc_cache)         │
   └─────────────────────────────────────────────────────────────────┘
                                                 │
                                                 ▼
                        ┌──────────────────────────────┐
                        │ polling: GET /api/material-  │
                        │ jobs → stage/bytes/spp UI    │
                        └──────────────────────────────┘
```

---

## 단계별 상세 — 부하 분류

각 단계마다: **(1) 소요 시간 추정, (2) 누가 일하나 (CPU/GPU/디스크/네트워크), (3) 메모리 영향, (4) 병목 여부**.

### Stage 0 — HTTP request → handler

| | |
|---|---|
| 소요 | < 1 ms |
| 일하는 곳 | CPU (HTTP parser) |
| 메모리 | — |
| 병목? | 아님 |

캐시 PNG 가 이미 있으면 (`measured_out.exists()`) 여기서 끝 — disk read 만으로 200 응답.

### Stage 1 — Variant set (`_ensure_mitsuba_variant`)

`mi.set_variant("cuda_rgb")` 등.

| | |
|---|---|
| 소요 | **첫 호출**: 1~3 s (Dr.Jit JIT 초기화, CUDA context 생성, kernel 캐시 로드). **이후**: ~0 ms (cache hit) |
| 일하는 곳 | CPU + GPU (CUDA context init) |
| 메모리 | GPU: 수백 MB (CUDA context + Dr.Jit pool) |
| 병목? | **첫 호출만** 무거움. 데몬 재기동 직후 첫 렌더는 추가 1~3s 더 걸림 |

### Stage 2 — `_build_scene_dict(bsdf, size, spp)`

Python dict + `mi.ScalarTransform4f.look_at(...)` 같은 작은 mi 객체 생성.

| | |
|---|---|
| 소요 | < 5 ms |
| 일하는 곳 | CPU |
| 메모리 | 무시 (KB) |
| 병목? | 아님 |

### Stage 3 — `mi.load_dict(scene_dict)` ⚠️ 핵심 부하

dict → Mitsuba 의 `Scene` 객체 빌드. BSDF 가 **measured** (.pbsdf / .hpbrdf) 면 여기서 무거워짐.

#### 3a. Preset / Curated BSDF (작은 dict)

| | |
|---|---|
| 소요 | 50~200 ms |
| 일하는 곳 | CPU (parsing) + GPU (BSDF data 작은 양 upload) |
| 메모리 | GPU: 수 MB |
| 디스크 I/O | 0 |
| 병목? | 첫 호출이면 약간, 이후는 무시 |

#### 3b. Measured BSDF (.pbsdf, ~수십~수백 MB)

| | |
|---|---|
| 소요 | 0.5~3 s |
| 일하는 곳 | **디스크 read (mmap)** + **CPU (TensorFile 파싱)** + **GPU upload** |
| 메모리 | host RAM: 파일 크기만큼 (mmap), GPU: 비슷한 양 (interpolator table) |
| 디스크 I/O | 수십~수백 MB |
| 병목? | 디스크 (HDD/CIFS 면 더 큼) + GPU upload bandwidth |

#### 3c. Measured BSDF (.hpbrdf, **13 GB**) — 현재 OOM

| | |
|---|---|
| 소요 | **N/A — 현재 환경 (WSL2 RAM 12 GB) 에서 OOM** |
| 일하는 곳 | 디스크 read + 17 GB host-pinned 요청 → 실패 |
| 메모리 | host pinned: 17 GB 시도 (한도 64 KiB), GPU: 16 GB device 시도 |
| 디스크 I/O | 13 GB read 시도 |
| 병목? | **물리 RAM 자체 부족** (RAM < 파일 크기) |

→ 채널 분리 데이터 (`bean://yunseong/.../table_publish_final/`) 의 단일 .pbrdf (191 MB) 사용해야 한 채널씩 안전 로드.

### Stage 4 — Render loop (`_render_to_png` 의 chunk for-loop)

```python
for k in range(_adaptive_chunks(spp)):
    sub = np.array(mi.render(scene, spp=chunk_spp, seed=k+1), dtype=np.float32)
    accum = (accum * k + sub) / (k + 1)   # CPU running mean
```

#### 4a. `mi.render(scene, spp, seed)` — GPU kernel

| | |
|---|---|
| 소요 | spp + render size 비례. 192×192 spp=1024: ~0.3~1 s. 384×384 spp=2048: ~2~5 s |
| 일하는 곳 | **GPU 100%** (path tracing). 첫 호출이면 + JIT compile (수 초) |
| 메모리 | GPU: framebuffer (RGBA float32) = `W×H×4×4` bytes = 384²×16 = 2.3 MB (작음) |
| 디스크 I/O | 0 |
| 병목? | render size 작으면 GPU 못 살림 (kernel 너무 빨리 끝남, util 4%). 우리가 4월 28일에 supersample 2× + chunks 줄임으로 완화. |

#### 4b. `np.array(...)` — GPU→CPU sync

GPU buffer → numpy float32 array.

| | |
|---|---|
| 소요 | sync 자체는 ms, 하지만 그 전에 `mi.render` 의 모든 lazy kernel 완료 대기 |
| 일하는 곳 | PCIe (memory transfer) + CPU (memcpy) |
| 메모리 | CPU: framebuffer copy (~수 MB) |
| 병목? | chunk 수만큼 sync 발생. 8 chunks → 8번 sync. 우리가 adaptive chunks 로 1~2번으로 축소. |

#### 4c. Running mean — CPU numpy

| | |
|---|---|
| 소요 | < 5 ms (작은 buffer) |
| 일하는 곳 | CPU |
| 메모리 | 무시 |
| 병목? | 아님 |

### Stage 5 — Tone-map + gamma (CPU)

`rgb / (1 + rgb*0.55)` → `rgb ** (1/2.2)` → uint8 clip.

| | |
|---|---|
| 소요 | < 10 ms (384² 까지) |
| 일하는 곳 | CPU (numpy) |
| 메모리 | CPU: 추가 framebuffer copy |
| 병목? | 아님 |

### Stage 6 — PIL Lanczos downsample

384×384 → 192×192 (supersample=2 일 때).

| | |
|---|---|
| 소요 | 5~20 ms |
| 일하는 곳 | CPU (PIL) |
| 메모리 | CPU: 추가 image |
| 병목? | 아님 |

### Stage 7 — PIL save PNG

| | |
|---|---|
| 소요 | 10~50 ms (192² RGBA) |
| 일하는 곳 | CPU (zlib compress) + 디스크 write |
| 메모리 | — |
| 디스크 I/O | ~10~50 KB write |
| 병목? | 아님 |

### Stage 8 — `_release_gpu_pool()` cleanup

`gc.collect()` + Dr.Jit `flush_malloc_cache` / `flush_kernel_cache`.

| | |
|---|---|
| 소요 | 5~50 ms (정상), 큰 tensor 해제 시 100ms+ |
| 일하는 곳 | CPU + GPU (메모리 해제) |
| 메모리 | GPU: 수 MB ~ 수 GB **해제** |
| 병목? | 아님. 안 하면 다음 렌더 OOM 가능. |

---

## 한 번 렌더의 wall time 추정 (정상 케이스)

**Preset / Curated, spp=2048, 192×192 → 384×384 supersample, cuda_rgb variant, 캐시 warm**:

| Stage | 추정 |
|---|---|
| 1. variant set (cached) | ~0 ms |
| 2. build dict | < 5 ms |
| 3. load_dict | 50 ms |
| 4. render (chunks=2 × spp=1024 × 384²) | 2~4 s ⚠️ 핵심 비용 |
| 5. tone-map | < 10 ms |
| 6. resize | 10 ms |
| 7. save PNG | 30 ms |
| 8. cleanup | 20 ms |
| **합계** | **~3 s** |

**첫 렌더 (variant + JIT 첫 컴파일 포함)**: 위 + 1~3 s = **~4~6 s**.

**Measured (.pbsdf 작은 거)**: render 시간은 비슷, load_dict 가 +1~3 s.

**hpBRDF .hpbrdf 13 GB**: load_dict 자체가 OOM → 0 s 만에 throw.

---

## 동시성 / 직렬화

```
Request A ──┐
Request B ──┤  →  HTTP threads (병렬)
Request C ──┘
                              │ 모두 _mitsuba_render_lock 대기
                              ▼
                    ┌──────────────────────┐
                    │  ONE BG render       │  ← Dr.Jit variant 가 process-global
                    │  thread at a time     │     이라 thread 병렬 불가
                    └──────────────────────┘
```

→ 25개 큐레이션 일괄 재렌더 시 **순차 처리**, GPU 가 burst → idle 반복. 진정한 병렬은 multiprocess 만 (오버헤드 큼, skip).

---

## 부하 종류별 정리

### CPU 부하

| 단계 | 비중 |
|---|---|
| variant init (첫 호출) | ★★★ |
| load_dict (parsing) | ★★ (measured 면 ★★★) |
| running mean (chunks) | ★ (chunks 적으면 ★) |
| tone-map + gamma | ★ |
| PIL resize + save | ★~★★ |
| cleanup (gc) | ★ |

### GPU 부하

| 단계 | 비중 |
|---|---|
| variant init (CUDA context) | ★★ (한 번) |
| BSDF data upload (measured) | ★★★ (큰 파일이면) |
| kernel JIT compile (첫 render) | ★★ (한 번) |
| **path tracing (`mi.render`)** | **★★★★★** (지속, 핵심 work) |
| sync barrier (chunks) | ★ |
| memory free (cleanup) | ★ |

### 디스크 I/O

| 단계 | 비중 |
|---|---|
| measured BSDF read | ★★★ (.pbsdf 수십~수백 MB) / ★★★★★ (.hpbrdf 13 GB, OOM) |
| PNG write | ★ (수십 KB) |

### 호스트 RAM

| 단계 | 비중 |
|---|---|
| BSDF mmap (measured) | ★★★ (.pbsdf 수십 MB) / **★★★★★ (.hpbrdf 13 GB, RAM 부족)** |
| framebuffer copy (sync) | ★ (수 MB) |

### 네트워크

평소엔 0. 단, BSDF 가 CIFS (`/bean`, `/bean_yunseong`) 위에 있으면 mmap = 네트워크 read → I/O latency 더 큼.

---

## 병목 진단 가이드

| 증상 | 의심 원인 | 확인 방법 |
|---|---|---|
| GPU util 낮은데 wall time 길다 | render size 너무 작음 / chunks 많아서 sync barrier overhead | `nvidia-smi -l 1` 으로 util 패턴 보기 (burst-idle 반복) |
| 첫 렌더만 느림, 이후 빠름 | variant init + JIT compile | 두 번째 렌더는 ~1s 짧으면 정상 |
| Measured 렌더 시 디스크 spike | 큰 .pbsdf mmap | `iostat -x 1` 또는 `iotop` |
| 호스트 RAM 부족, swap thrash | hpBRDF 같은 대용량 measured | `free -h` 로 swap 활성도 |
| OOM (`gpu_oom` status) | 누적 leak 또는 BSDF 자체가 큼 | 데몬 재기동 후에도 fail 하면 BSDF 가 절대적으로 큰 것 |
| 모든 렌더가 한 번에 한 개씩만 진행 | `_mitsuba_render_lock` 직렬화 | 정상. 병렬은 multiprocess 만 가능 |
| GPU memory leaked (`device memory: 16 GiB`) | 실패 후 cleanup 누락 | 우리는 `_release_gpu_pool()` 로 처리 — 그래도 누수 보이면 cleanup path 점검 |

---

## 측정 도구 cheat sheet

```bash
# 실시간 GPU util / mem
nvidia-smi -l 1

# 호스트 메모리
free -h

# 디스크 I/O
iostat -x 1
iotop -o     # 프로세스별

# 데몬 자체 메모리 / CPU
top -p $(pgrep -f run_render_daemon)

# 렌더 wall time 측정 (smoke)
PYTHONPATH=/home/jinnyeong/robomituba-build/mitsuba3/python:/home/jinnyeong/.local/lib/python3.10/site-packages \
  /usr/bin/python3.10 -c "
import time, mitsuba as mi
mi.set_variant('cuda_rgb')
from mitsuba_converter.sphere_preview import _build_scene_dict, _render_to_png
from pathlib import Path
bsdf = {'type':'roughplastic','distribution':'ggx','alpha':0.1}
scene = _build_scene_dict(bsdf, size=384, spp=2048)
t = time.perf_counter()
_render_to_png(scene, Path('/tmp/test.png'),
               variant='cuda_rgb', spp=2048, supersample=2, target_size=192)
print(f'{time.perf_counter()-t:.2f}s')
"
```

---

## 우리가 4월 28일에 적용한 최적화 (반영분)

| 변경 | 어떤 부하 줄였나 |
|---|---|
| chunks 8 → adaptive (1~4) | GPU↔CPU sync barrier 줄임 (4b stage) |
| supersample 2× (192→384) | GPU 활용도 ↑ (4a stage 의 kernel 이 길어져 clock 부스트) |
| max_depth 8 → 5 | path tracing ray 당 비용 ~30% ↓ (4a stage) |
| `cuda_rgb` / `cuda_spectral` (non-AD) | GPU 메모리 ~30% ↓, JIT overhead ↓ (1, 4a) |
| `_release_gpu_pool()` finally | 실패 후 GPU memory leak 방지 (8 stage) |

---

*마지막 업데이트: 2026-04-30*
