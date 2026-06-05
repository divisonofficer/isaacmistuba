# 작업 로그 · 2026-04-21 ~ 04-30

10일간 한 일을 한 페이지로.

---

## TL;DR

- **컨트롤 플레인 UI** — 평탄한 버튼들 → 스텝형 액션 바, Tooltip 친절 메시지, 작업 큐 + 결과 토스트로 「뭐가 됐고 뭐가 실패했는지」 명확.
- **다운로드 인프라** — hpBRDF (Hugging Face, 14×13 GB) 다운로드 가능. 진행률·속도·ETA 표시. `/mnt/d` 같은 외부 디스크에 저장 경로 override.
- **Mitsuba 재빌드 + KAIST 패치** — `cuda_rgb` / `cuda_spectral` (non-AD) 변종 추가, hpBRDF `.hpbrdf` 로드 활성화.
- **Sphere preview 최적화** — GPU util 4% 원인 분석 → chunks/supersample/max_depth/메모리 cleanup 5가지 적용.
- **미해결**: hpBRDF 1개 = 13 GB가 WSL2 RAM (12 GB) 보다 커서 OOM. 채널 분리 데이터 (bean 의 14×68 파일) 로 우회 전략 분석 완료, 구현은 다음 작업.

---

## 커밋 (4건)

| 일자 | 해시 | 한 줄 |
|---|---|---|
| 04.23 | `e277237` | webui + daemon updates |
| 04.23 | `9017f9c` | webui density polish + Quick Actions SVG icons |
| 04.24 | `2ecae78` | GPU 로딩 sub-progress + Dr.Jit 가드 + 진행 카드 폴리싱 |
| 04.28 | `9909c7e` | BRDF preview renderer |

이외 hpBRDF 다운로드, 사용자 설정, 채널 분리 카탈로그 등은 **미커밋** (현재 작업 진행 중).

---

## 일자별

### 4월 21~23일 — UI 리디자인

- 세션 카드 흡수, 하단 탭을 세로로 변환, `.cs-root` gap 압축
- topbar 의 4-버튼을 **스텝형 액션 바** 로: `[연결됨 ✓] [장면 준비됨 ✓] [동기화] ▶[렌더]` (chip + button + primary CTA 3-tier)
- Isaac 끊겨도 액션 그룹 안 사라지게 — `currentSceneIdStore` 도입해서 마지막 scene ID fallback

### 4월 24일 — 진행 가시성 (커밋 `2ecae78`)

- **Dr.Jit 인터프리터 가드**: 데몬 시작 시 `import drjit, mitsuba` 검증. 실패 시 정확한 launch 명령 안내 후 exit.
- **`loading_scene` 5-phase 분해**: `mi.load_file()` 직전에 `parsing_xml → loading_meshes → uploading_textures → compiling_optix` emit, 끝나면 `ready`. 캐시 적중 시 `cached` 단일 이벤트.
- 「준비」 → **「장면 준비」** 라벨, 렌더 버튼 「렌더 중」 spinner + pulse, 진행 카드 정보 계층 재배치 (제목 → progress bar → 현재 단계 강조 → 체크리스트 → 기술 로그 (접힘)).

### 4월 24~25일 — Tooltip 강화

- `Tooltip.svelte` — `title` (굵은 헤딩) + `text` (본문) 2단, 글씨 키움 (xs → sm), 패딩 키움.
- Connect / Prepare / Sync / Render 버튼 모두 Tooltip 으로 교체. 비활성 사유별 친절 본문 (예: 「먼저 연결이 필요해요」 — 「[연결] 버튼으로 Isaac Sim 세션을 활성화한 뒤 렌더할 수 있어요.」)
- 3D Blueprint 「장면 준비」 버튼도 동일.
- 재질 뷰어는 처음엔 친절 메시지 → 사용자 피드백 「설명 너무 많다」 → **이름만** 으로 단순화.

### 4월 25일 — 작업 결과 가시성

- **결과 토스트**: 우측 하단에 ✓ 「장면 준비 완료 · 12s」 / ✕ 「동기화 실패 · 3s」 (`commandResultToasts` store, dedupe by command_id, 6.5s TTL).
- **작업 큐 통합**: 기존엔 render job 만 보였는데, Isaac commands 도 `recentIsaacCommands` 폴링해서 같이 표시. 종결된 명령 클릭 시 `isaacHistoryCard` (✓/✕ + 메시지 + 경과시간 + technical log).

### 4월 25~26일 — Frontend freeze 진단

증상: 화면 가끔 먹통, `npm run dev` 재시작하면 회복.

진단 순서:
1. Tooltip `onDestroy` cleanup, toast Set bound 200, isaac history cap 30 → 누수 후보 차단
2. 데몬 직접 접속 (`http://127.0.0.1:8765/`) 으로도 동일 → vite 무관
3. 데몬 로그 `/health 200`, 브라우저 8s abort
4. WSL 안에서 `curl /health` → **0.06s** → **WSL2 wslhost 포워딩 stall** 확정

해결: `wsl --shutdown` 단기 처방, 또는 prod 빌드 직접 사용.

### 4월 27일 — hpBRDF 다운로드 + 저장 경로 override

- 카탈로그에 `hf-dataset://` URL 스킴 도입. hpbrdf_2025 의 14개 material 다운로드 가능.
- **사용자 설정** `~/.robomituba/settings.json`:
  - `dataset_storage_overrides` — 예: `{"hpbrdf_2025": "/mnt/d/hpbrdf"}` → C: 가 작은 WSL 환경에서 외부 디스크로 우회
  - 새 endpoint `GET/POST /api/user-settings`, Settings 페이지에 「데이터셋 저장 경로」 패널
- 13 GB × N 파일 다운로드 전 confirm dialog (실수 클릭 방지).

### 4월 27~28일 — 다운로드 진행도 (3차 시도 끝에 성공)

| 시도 | 방법 | 결과 |
|---|---|---|
| 1 | `hf_hub_download(tqdm_class=...)` | **0%** — Xet 백엔드가 tqdm callback 우회 |
| 2 | filesystem watcher (dest size polling) | **0%** — Xet 은 chunk-addressed cache 에 받고 끝에 한 번에 dest 로 assemble |
| 3 | **자체 streaming** (`requests` + resolve URL + `Range`) | **OK** ✓ |

- 작업 큐에 다운로드도 통합 (`_create_material_job(action="redownload")`)
- 3초 rolling window 로 즉시 속도 계산, 200 ms 마다 UI 업데이트
- 「단계」 컬럼: `Aluminum.hpbrdf · 5.2 GB / 12.1 GB (43%) · 22.4 MB/s` + 4px 진행 바 + `↓ ETA 6m 18s`

### 4월 28일 — Mitsuba 빌드 + hpBRDF 패치 + sphere preview 최적화 (커밋 `9909c7e`)

**Sphere preview 최적화 (코드만)**:
- chunks 8 → adaptive (spp ≤ 1024 면 1, 그 외 2~4)
- 192² 대신 384² 렌더 후 PIL Lanczos 로 192 downsample (GPU saturation up, sharper anti-alias)
- max_depth 8 → 5

**Mitsuba 재빌드**:
- `mitsuba.conf` enabled 에 `cuda_rgb` + `cuda_spectral` 추가 (AD 머신 제거 → ~2× 빠름)
- `cmake --build . -j32` (~수 분)
- `_RGB_ORDER` 우선순위: `cuda_rgb → cuda_spectral → cuda_ad_spectral`

**hpBRDF KAIST 패치**:
- `git clone https://github.com/yunseong0518/hpBRDF` → `third_party/hpbrdf_patch/measured_polarized.cpp` 에 배치
- `scripts/apply_hpbrdf_patch.sh` (backup + copy + rebuild 안내)
- 변경: `wavelengths[5]` 고정 배열 → 동적 길이 (68 등 임의 wavelength 지원)
- sphere_preview 의 `.hpbrdf` 차단 해제

**부수 픽스**:
- `run_control_plane_dev.sh` — sudo 환경에서 `typing_extensions` 못 찾던 문제 (SUDO_USER 의 `~/.local/lib/python3.10/site-packages` 을 PYTHONPATH 에 끼워줌)
- **GPU memory cleanup on failure**: 매 render 끝에 `_release_gpu_pool()` (gc + Dr.Jit `flush_malloc_cache`). 이전엔 hpBRDF 로드 실패 시 `device memory: 16 GiB leaked` 명시적 누수.
- **`gpu_oom` 새 status**: OOM 메시지 패턴 잡아서 친절 본문으로 매핑 (「GPU/host-pinned 메모리 부족 — hpBRDF 는 파일당 13 GB 라 다른 큰 작업 종료 후 재시도하세요」)

### 4월 28일 — 사용자 spp 설정

- `material_preview_spp` (16~16384) — 설정 페이지에 숫자 input + 6 프리셋 (256/1024/2048/4096/8192/16384) + 「기본값」 토글
- 큐레이션 default 2048, 측정 default 384 — 사용자 설정 시 둘 다 적용
- 작업 테이블에 `spp=N` inline 표시

### 4월 29~30일 — hpBRDF 한계 + 우회 분석

**진단**:

| 자원 | 현재 | hpBRDF 요구 |
|---|---|---|
| WSL2 RAM | **12 GB** | 13 GB |
| memlock (pinned) | **64 KiB** | 17 GB |
| GPU free | **817 MiB** (Windows 가 31 GB 점유) | ~16 GB |

→ 코드로는 해결 불가. **시스템 자원 문제**.

**채널 분리 데이터 발견** — `\\bean.postech.ac.kr\data\yunseong\hpbrdf\table_publish_final`:
- 14 material × 68 채널 (`414.pbrdf` ~ `726.pbrdf`, 각 191 MB)
- 단일 .pbrdf = `M[361, 91, 91, 1, 4, 4]` (1 wavelength)
- **표준 패치 plugin 으로 정상 로드 확인** ✓
- VRAM 65× 감소 (13 GB → 191 MB / channel)

`/bean_yunseong` CIFS 마운트 + `material_library.py` 에 `hpbrdf_channels_dir` 헬퍼 추가 (디스패치 정책 진행 중, 미완성).

---

## 현재 상태

### 환경 변경 (재기동 / 재빌드 필요한 것)

| 항목 | 변경 |
|---|---|
| `~/.wslconfig` (호스트) | `memory=12GB` (이게 hpBRDF 한계의 직접 원인 — 늘리면 풀림) |
| `mitsuba.conf` | `cuda_rgb`, `cuda_spectral` 추가 + 재빌드 완료 |
| `modules/mitsuba3/src/bsdfs/measured_polarized.cpp` | KAIST 패치 적용 (backup `.upstream.bak`) |
| `~/.robomituba/settings.json` | 사용자 설정 (저장 경로 + spp) |
| `/bean_yunseong` | 신규 CIFS 마운트 (yunseong 채널 데이터) |

### 미커밋 변경 (작업 진행 중)

- `material_library.py` — HF URL, 채널 분리 helpers
- `render_daemon.py` — streaming downloader, 속도 추적, gpu_oom mapping
- `sphere_preview.py` — adaptive chunks, supersample, GPU cleanup, max_depth, .hpbrdf 활성화
- 신규: `material_overrides_store.py`, `scripts/apply_hpbrdf_patch.sh`, `third_party/hpbrdf_patch/`, `tools/hpbrdf/`

### 다음 액션

1. **채널 분리 렌더 구현** — sphere_preview 의 `.hpbrdf` 분기를 채널 폴더 발견 시 `_render_channel_split` 으로 디스패치
2. **Quick (3~5 ch) vs Full (68 ch) 정책 결정**
3. **Bean 데이터** — CIFS 직접 read vs 로컬 캐시
4. **WSL2 RAM 늘리기** — 호스트 RAM 충분하면 `.wslconfig memory=24GB` + `wsl --shutdown`

### 알려진 한계

- hpBRDF preview = 채널 분리 path 없으면 OOM
- Mitsuba `_mitsuba_render_lock` 으로 동시 1 재질 (Dr.Jit variant process-global)
- WSL2 wslhost 가끔 stall → 데몬 직접 접속 (`http://127.0.0.1:8765/`) 권장
- HF Xet dedup 포기 (자체 streaming) — 13 GB 단일 파일엔 미미한 손해

---

*2026-04-30 작성. 다음 weekly progress: `docs/2026-05-04_weekly_progress_report.md`.*
