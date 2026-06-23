# 단일밴드 측정 pBRDF × RGB-albedo 최적화 — 품질·성능 트레이드오프 검토

*2026-06-23 · OpticalNav / Infinigen import 렌더 파이프라인*

## 0. 요약 (TL;DR)

- **현재 설계는 dev_report 6/17 "1안(Option 1)"대로 충실히 구현**되어 있다: 오브젝트별 측정 pBRDF를 R/G/B **3개 단일밴드 슬라이스(614/542/446 nm)**로 각각 평가해 RGB intensity를 만든 뒤, baked albedo 텍스처를 per-channel로 곱한다 (`measured_polarized_rgb.cpp`, `intensity *= albedo_scale`). 밴드당 **183 MB** (3밴드 549 MB).
- **제안(1밴드 BRDF × 3채널 albedo)의 3× 메모리/평가 절감은 실재**하며, **품질 영향은 재질에 따라 극명하게 갈린다**:
  - **유전체·확산 표면**(plaster/wood/fabric/plastic/painted/ceramic/glass/tile — 실내 표면의 대다수): specular가 본질적으로 **무채색**이라 1밴드로 거의 **무손실**. 색은 어차피 albedo가 담당.
  - **유색 금속**(gold/brass/copper): BRDF 자체가 **유색 specular** → 1밴드로 붕괴 시 특유의 색 하이라이트 상실. **품질 손실 큼**.
  - **무채색 금속**(aluminum, steel/suj2, chrome, nickel): 반사가 평평한 그레이 → 밴드 간 차이 미미 → **1밴드 충분**.
- **권장: 재질별 하이브리드.** 유전체 + 무채색 금속은 1밴드(3× 절감), **유색 금속만 3밴드** 유지. 우리 hpbrdf 금속 집합에서 3밴드가 꼭 필요한 건 사실상 **`fake_gold` 한 종**뿐.
- **보너스(Phase 0 우회):** 1밴드 경로는 production에 **이미 빌드된** `measured_polarized`(단일 파일) 플러그인을 쓴다. 미빌드된 `measured_polarized_rgb`(Phase 0 블로커) 없이도 무채색 금속이 **색으로 렌더**될 수 있다 — `measured_polarized.cpp`에 `albedo_scale` 지원만 추가하면 됨.

---

## 1. 현재 설계 검증 (1안 충실도)

| 항목 | 설계 (6/17 보고서) | 구현 | 일치 |
|---|---|---|---|
| 전략 | 오브젝트별 단일 pBRDF × albedo 텍스처 | `measured_polarized` + `albedo_scale` | ✅ |
| RGB 형성 | (암묵) 대표 재질의 분광 응답 | **3밴드** 614/542/446 각각 eval → R/G/B | ✅ |
| albedo 적용 | pBRDF intensity에 텍스처 곱 | `intensity *= clamp(albedo_scale,0,1)` (per-channel) | ✅ |
| albedo 소스 | 기존 asset base_color | Infinigen Cycles DIFFUSE bake (map_Kd) | ✅ |
| 비용 | — | 밴드당 **183 MB**, 3밴드 **549 MB** | — |

구현 위치: `modules/mitsuba3-optix7/src/bsdfs/measured_polarized_rgb.cpp`(`filename_r/g/b` 로드 + 3밴드 eval + albedo 곱), `multimodal.py:_convert_channel_split_measured_bsdfs_to_rgb_plugin`(R=614/G=542/B=446 배선), `render_daemon.py:_append_measured_albedo_scale_xml`. **결론: 설계대로 정확히 구현됨.**

> 참고로 production 빌드에 `measured_polarized_rgb`가 빠져 luminance fallback(흑백)이 도는 알려진 이슈는 본 검토와 별개이며, 아래 §6의 1밴드 경로가 이를 **부수적으로 우회**한다.

---

## 2. 핵심 물리 — "색"은 BRDF에서 오는가, albedo에서 오는가

RGB 렌더에서 한 픽셀의 색 = **BRDF intensity(λ) × albedo(λ) × 조명(λ)** 을 R/G/B 3채널로 적분한 것. 색의 출처는 둘:

1. **BRDF의 분광 의존성** — 특히 **도체(conductor)**는 복소 굴절률 n(λ), k(λ)가 파장에 따라 달라 **유색 specular**를 만든다. 금은 R·G 대역에서 ~98% 반사(노란빛), 구리는 R 93%/G 70%(붉은빛) [참고 3].
2. **albedo 텍스처** — 공간적 색 변조(나무결, 페인트색 등).

- **3밴드 방식**: 두 출처를 모두 보존(BRDF의 유색 specular + albedo의 공간색).
- **1밴드 방식**: BRDF를 **무채색(achromatic) angular shape**으로 만들고, **색을 전적으로 albedo에 위임**. → BRDF의 고유 분광색은 사라진다.

따라서 핵심 질문은 **"이 재질의 색이 BRDF에 있느냐, albedo에 있느냐"** 로 환원된다.

---

## 3. 언제 1밴드가 충분하고, 언제 깨지는가 — PBR metallic workflow의 정설

업계 표준 PBR **metallic workflow**가 이 질문에 정확한 답을 준다 [참고 1]:

- **유전체(비금속)**: specular 반사율 **F0 ≈ (0.04, 0.04, 0.04) — 무채색**. 즉 코트의 Fresnel·roughness·angular 응답이 사실상 **파장 무관**. 색은 전적으로 **diffuse albedo**가 담당.
  - → **1밴드 BRDF × RGB albedo = 거의 무손실.** "base color = 비금속의 diffuse albedo" [참고 1]와 정확히 일치.
- **금속(도체)**: F0 = **재질색(유색 specular)**. "base color = 금속의 specular color" [참고 1].
  - **유색 금속(gold/copper/brass)**: BRDF가 유색 → 1밴드 붕괴 시 하이라이트가 무채색이 되고, albedo만으로 색을 흉내 → 특유의 금속 광택 상실. **손실 큼.**
  - **무채색 금속(aluminum/steel/chrome/nickel)**: 반사 스펙트럼이 거의 평평한 그레이 → 밴드 간 intensity 차이 미미 → **1밴드 충분.**

분광 vs RGB의 더 큰 맥락 [참고 2]: broad-spectrum 조명(실내 ambient/area light)과 비포화 재질에서는 RGB ≈ 분광이 성립한다. 차이는 **좁은밴드 광원**이나 **고채도 재질·금속 하이라이트 + 복잡 조명**에서만 두드러진다. 우리 렌더는 이미 채널분할 **RGB 근사**라 분광 정확도는 애초에 포기되어 있고, 1밴드는 그 근사를 **유전체엔 거의 영향 없이, 유색 금속엔 누적**시키는 한 단계일 뿐이다.

---

## 4. 우리 재질 집합에 대입

hpbrdf_2025 금속 채널과 Infinigen optical_class 매핑 기준:

| 재질 군 | 색의 출처 | 1밴드 영향 | 권장 밴드 |
|---|---|---|---|
| 유전체·확산 (plaster/wood/fabric/plastic/painted/ceramic/tile) | albedo | 무시 가능 | **1밴드** |
| 유리 (dielectric/roughdielectric) | albedo/투과 | 무시 가능 | **1밴드** |
| `aluminum` (무채색 금속) | 평평 그레이 | 미미 | **1밴드** |
| `suj2`(steel, 무채색) | 평평 그레이 | 미미 | **1밴드** |
| `fake_gold` (유색 금속) | **BRDF 유색 specular** | **큼** | **3밴드 유지** |
| (향후) copper/brass | BRDF 유색 | 큼 | 3밴드 |

→ **현재 scene에서 3밴드가 꼭 필요한 건 gold 계열 1종.** 나머지(압도적 다수)는 1밴드로 **3× 메모리·평가 절감**을 가져갈 수 있다. VRAM이 다재질 scene에서 측정 테이블 잔류로 압박되는 점(밴드당 183 MB × 재질 수)을 감안하면 실질 이득이 크다.

> 단 **최악 케이스 주의**: albedo가 무채색(흰 텍스처)인 **유색 금속**을 1밴드로 처리하면 색이 완전 소실된다(BRDF에도 albedo에도 색이 없음). 유색 금속 판정은 보수적으로.

---

## 5. 성능 이득의 정확한 범위

- **메모리**: 재질당 549 MB → 183 MB (**3×**). GPU 상주 측정 테이블이라 다재질 scene에서 직접적 VRAM 절감.
- **평가 비용**: BSDF eval당 테이블 보간 3회 → 1회 (**3×** 적음). 단 path tracing 총시간에서 BSDF eval이 차지하는 비중에 비례하므로 **전체 렌더 3× 빨라진다는 뜻은 아님** — 메모리·테이블 로드·BSDF 비중만큼 단축.
- **로드/초기화**: 측정 파일 파싱 3개 → 1개.

---

## 6. 권장안 — 재질별 하이브리드 밴드

1. **밴드 수를 optical_class로 결정** (`apps/import_infinigen_scene.py:_material_binding`):
   - 유전체·확산·유리·**무채색 금속(aluminum/steel)** → `band_mode: "single"`(1밴드).
   - **유색 금속(gold/brass/copper)** → `band_mode: "rgb"`(3밴드, 현행).
2. **렌더 staging 분기** (`multimodal.py`/`render_daemon.py`):
   - single → 단일 `measured_polarized`(대표 visible 밴드, 예: 542 nm) + `albedo_scale`(RGB 텍스처).
   - rgb → 현행 `measured_polarized_rgb`(3밴드) + `albedo_scale`.
3. **플러그인 보강**: `measured_polarized.cpp`(단일밴드)에 **`albedo_scale` 텍스처 곱 추가** (현재 RGB 플러그인에만 있음). 작은 C++ 변경.
4. **검증 실험**: 동일 viewpoint를 1밴드 vs 3밴드로 렌더해 **ΔE(CIELAB) 맵** 비교.
   - 예상: 유전체·무채색 금속 ΔE ≈ 0–2(무시), gold ΔE 크게(특히 하이라이트). 이 임계로 자동 분류 규칙을 보정.

### 보너스 — Phase 0 우회
단일밴드 경로는 production에 **이미 컴파일된** `measured_polarized`만 사용한다. 미빌드된 `measured_polarized_rgb`(현재 흑백 fallback 원인) 없이도, **무채색 금속이 albedo 색으로 즉시 렌더**된다 — `measured_polarized.cpp`에 `albedo_scale`만 추가하면 됨. 즉 1밴드 최적화는 성능뿐 아니라 **현재 흑백 이슈의 부분적 해법**이기도 하다.

---

## 7. 카베아트 / 한계

- **편광**: 측정 pBRDF의 Mueller 행렬도 약하게 파장 의존적이다. 1밴드는 분광 편광 변화를 상실하나, 대체로 작고 우리 용도(편광 신호 존재 여부·대략적 DoLP/AoLP)에는 영향이 제한적이다. 유색 금속의 편광은 3밴드 유지로 보존.
- **무채색 albedo × 유색 금속** 조합은 1밴드의 최악 케이스(색 소실) — §4 주의.
- 본 검토는 RGB 워크플로 내 1밴드 vs 3밴드 비교다. 진짜 분광 정확도(좁은밴드 광원 등)는 두 방식 모두 근사이며 별개 트랙.

---

## 참고자료

- [PBR 이론 — F0, metallic workflow (LearnOpenGL)](https://learnopengl.com/PBR/Theory) · [PBR material workflow / metalness (TurboSquid)](https://blog.turbosquid.com/2023/07/27/an-intro-to-physically-based-rendering-material-workflows-and-metallic-roughness/) — 유전체 F0≈0.04 무채색, 금속 F0=base color(유색 specular).
- [Spectral rendering, part 3: Spectral vs. RGB (Moments in Graphics)](https://momentsingraphics.de/SpectralRendering3Results.html) · [Picture-Perfect RGB Rendering using Spectral Prefiltering (Ward & Eydelberg-Vileshin)](https://www.thevespiary.org/library/Files_Uploaded_by_Users/no1uno/pdf/Instrumentation/RGB%20to%20Spectra/Ward.EydelbergVilshin.Picture.Perfect.RGB.Rendering.using.Spectral.Prefiltering.and.Sharp.Color.Primaries.pdf) — broad-spectrum/비포화에서 RGB≈분광, 포화 금속·좁은밴드에서만 발산.
- [PBR Book 4e §9.4 Conductor BRDF](https://www.pbr-book.org/4ed/Reflection_Models/Conductor_BRDF) · [Modeling the BRDF from spectral reflectance of metallic surfaces (ResearchGate)](https://www.researchgate.net/publication/264043937_Modeling_the_BRDF_from_spectral_reflectance_measurements_of_metallic_surfaces) — 도체 n(λ),k(λ) → 유색 specular(gold R+G 98%, copper R 93%/G 70%).
- [Mitsuba 3 BSDF plugins](https://mitsuba.readthedocs.io/en/stable/src/generated/plugins_bsdfs.html) — `measured` / measured polarized 플러그인.

*(본 보고서는 코드 검증 + 웹 참고자료 기반. 정량 확인은 §6.4 ΔE 실험 권장.)*
