# Mitsuba 3 BRDF / Polarization / NIR Implementation Guide
Version: 2026-04-17  
Audience: implementation agent  
Language: Korean (with English identifiers / code)  
Status: actionable working guide

---

## 0. Goal

이 프로젝트의 목표는 **Mitsuba 3에서 최대한 많은 공개 다운로드 가능한 material 자산을 활용**하되, 우선순위를 아래 순서로 두는 것이다.

1. **true polarization 지원**
2. **NIR(near-infrared) 지원**
3. **material 종류 확장**
4. **Mitsuba 3 적용 난이도 최소화**
5. **향후 변환/피팅 파이프라인 확장 가능성 확보**

이 가이드는 **연구 메모가 아니라 구현 지침서**다.  
Agent는 아래의 규칙과 단계에 따라 환경을 구성하고, 데이터셋을 다운로드/정리하며, Mitsuba 3 렌더링 파이프라인을 단계적으로 확장해야 한다.

---

## 1. Executive summary

### 1.1 핵심 결론

- **Polarization + NIR를 동시에 만족하는 공개 데이터셋의 핵심은 hpBRDF**
- **Polarization 파이프라인의 가장 쉬운 스타터는 KAIST pBRDF**
- **NIR material 수를 빠르게 늘리는 가장 실용적인 자산은 RGL material database**
- **UTIA / MERL / OpenSVBRDF는 재질 다양성 확장용이지만, measured polarization의 직접 대체재가 아니다**

### 1.2 데이터셋 그룹

#### Group A — `native_measured_polarized`
Mitsuba 3의 `measured_polarized`와 직접적으로 연결되는 계열.

- **KAIST pBRDF (2020)**  
  - 25 isotropic pBRDFs
  - visible 5 bands
  - Mitsuba용 `.pbsdf` 직접 제공
  - 편광 파이프라인 검증용 1순위

- **hpBRDF (2025)**  
  - 14 materials
  - 414–950nm, 68 bands
  - visible + NIR + full Mueller matrix
  - Mitsuba 3 source patch 필요
  - 본 연구용 핵심 데이터셋

#### Group B — `native_measured_spectral`
Mitsuba 3의 `measured` 플러그인으로 바로 쓰기 좋은 계열.

- **RGL material database**
  - 360–1000nm spectral BRDF
  - `_spec.bsdf` directly usable
  - Mitsuba plugin / Python loader / Tekari viewer 존재
  - true measured polarization은 아님
  - NIR material bank로 매우 유용

#### Group C — `conversion_or_fitting_targets`
공개 다운로드는 가능하지만 Mitsuba 3에 바로 연결하기보다 변환/피팅이 필요한 계열.

- **UTIA BRDF database**
- **MERL BRDF database**

#### Group D — `svbrdf_asset_bank`
strict homogeneous BRDF가 아니라 material asset 확장용.

- **OpenSVBRDF**
  - 1,000+ samples
  - GGX parameter maps / normal / tangent / transparency
  - principled / GGX-style analytic material 파이프라인으로 연결

---

## 2. Non-negotiable rules

Agent는 아래 규칙을 반드시 지킨다.

### Rule 1
**true polarization 실험에는 Group A만 source-of-truth로 사용한다.**

즉:
- KAIST pBRDF
- hpBRDF

만 measured polarization ground truth로 간주한다.

### Rule 2
**NIR + polarization이 동시에 필요한 실험의 canonical source는 hpBRDF 하나뿐이라고 가정한다.**

### Rule 3
**RGL / UTIA / MERL / OpenSVBRDF는 measured polarization이 아니다.**  
이들은 material appearance / spectral range / diversity 확장용이다.

### Rule 4
동일하거나 유사한 material label이 서로 다른 데이터셋에 등장하더라도,
**같은 물리 샘플이라고 가정하지 않는다.**

예:
- `Fake gold` in KAIST pBRDF
- `Fake gold` in hpBRDF

같은 이름이어도 acquisition setup, calibration, spectral coverage, polarization treatment가 다를 수 있으므로
**동일 물질 샘플로 묶지 않는다.**

### Rule 5
Agent는 material ingest를 아래 우선순위로 구현한다.

1. `measured_polarized` (pBRDF)
2. patched `measured_polarized` (hpBRDF)
3. `measured` (RGL spectral `.bsdf`)
4. conversion/fitting stubs (UTIA / MERL)
5. parameter-map ingestion (OpenSVBRDF)

---

## 3. Dataset inventory

## 3.1 KAIST pBRDF (SIGGRAPH 2020)

### What it is
- 25 isotropic pBRDFs
- five wavelength ranges in the visible spectrum
- per-material `[matlab]` and `[mitsuba]` downloads available
- Mitsuba용 `.pbsdf` directly distributed

### Material list from official dataset page
1. Spectralon
2. White billiard
3. Chrome
4. Black billiard
5. Brass
6. Gold
7. Fake gold
8. Red billiard
9. Blue billiard
10. Green billiard
11. ZrO2
12. Fake pearl
13. Yellow silicone
14. Ceramic alumina
15. White silicone
16. Pink silicone
17. PEEK
18. SUJ2
19. Mint silicone
20. Ocher silicone
21. POM
22. Lightgreen silicone
23. Purple silicone
24. Blue silicone
25. Orange silicone

### Family analysis
- **Metals / metal-like:** Chrome, Brass, Gold, Fake gold, SUJ2
- **Billiard / glossy colored polymers:** White/Black/Red/Blue/Green billiard
- **Silicones:** Yellow, White, Pink, Mint, Ocher, Lightgreen, Purple, Blue, Orange
- **Engineering polymers:** PEEK, POM
- **Ceramic / oxide / pearl-like:** ZrO2, Ceramic alumina, Fake pearl
- **Reference diffuse standard:** Spectralon

### Why we care
- Mitsuba 3 문서의 `measured_polarized`가 직접 가리키는 canonical dataset
- implementation sanity check에 최적

### Download policy
- **Preferred:** official dataset page에서 material별 `[mitsuba]` 다운로드
- **Optional:** `[matlab]`도 함께 받아 calibration / inspection 용도로 보관

### Storage target
- `data/pbrdf_2020/raw/`
- `data/pbrdf_2020/mitsuba/`
- `data/pbrdf_2020/metadata/`

### Mitsuba role
- `native_measured_polarized`
- **first working milestone**

---

## 3.2 hpBRDF (SIGGRAPH Asia 2025)

### What it is
- 14 real-world materials
- full Mueller matrix
- 414–950nm
- 68 spectral bands
- visible + NIR
- official code repo provides a modified `measured_polarized.cpp`

### Material list from Hugging Face dataset files
1. Aluminum
2. Black glass
3. Black rough plastic
4. Fake gold
5. Gray silicone
6. Green silicone
7. Plum rough plastic
8. Red rough plastic
9. SUJ2
10. Silver rough plastic
11. White billiard
12. White rough plastic
13. White smooth plastic
14. Yellow rough plastic

### Family analysis
- **Metals / metal-like:** Aluminum, SUJ2, Fake gold
- **Dielectric smooth/transparent-ish:** Black glass
- **Silicones:** Gray silicone, Green silicone
- **Plastics / rough polymers:** Black/Plum/Red/Silver/White/Yellow rough plastic, White smooth plastic
- **Billiard-like polymer:** White billiard

### Why we care
- 이 프로젝트에서 **Polarization + NIR 동시 지원**의 중심
- source build와 patching을 감수할 가치가 있는 유일한 공개 measured dataset

### Download policy
- **Preferred:** Hugging Face dataset repo 전체 clone or download
- **Required:** GitHub repo의 `measured_polarized.cpp` 확보
- **Required:** material manifest 생성

### Storage target
- `data/hpbrdf_2025/raw/`
- `data/hpbrdf_2025/manifest/`
- `third_party/hpbrdf_patch/`

### Mitsuba role
- `patched_native_measured_polarized`
- **mainline research milestone**

---

## 3.3 RGL material database

### What it is
- isotropic / anisotropic BRDF database
- spectral coverage: 360–1000nm
- spectral `.bsdf` and RGB `.bsdf`
- Mitsuba plugin / reference implementation / Python loader / Tekari viewer available
- default license: CC0 unless otherwise noted

### Representative material families (official FAQ examples)
- metals
- paper
- car paints
- organic samples
- fabrics
- isotropic and anisotropic BRDFs

### Important caution
이 데이터는 **spectral BRDF**로는 매우 강력하지만,  
**measured polarization ground truth가 아니다.**

즉:
- NIR appearance / spectral reflectance 확장에는 좋다
- Mueller-matrix polarization 실험의 정답 데이터로 쓰면 안 된다

### Download policy
- official material database page에서 material 클릭
- `_spec.bsdf` 우선 다운로드
- RGB `.bsdf`는 fallback only
- Tekari viewer는 inspection tool로 optional 설치

### Storage target
- `data/rgl_bsdf/spec/`
- `data/rgl_bsdf/rgb/`
- `data/rgl_bsdf/raw/`
- `tools/tekari/` (optional)

### Mitsuba role
- `native_measured_spectral`
- **NIR material volume expansion**

---

## 3.4 UTIA BRDF database

### What it is
- 150 anisotropic BRDF measurements
- official category counts:
  - 96 fabric
  - 16 leather
  - 16 wood
  - 6 plastic
  - 6 carpets
  - 10 other

### Why we care
- fabric / leather / wood / carpet 계열의 재질감 확장
- anisotropy diversity가 좋음

### Important caution
- Mitsuba 3에 바로 꽂는 canonical route가 이 가이드 범위에서 확정되지 않음
- **raw data source**로 보관하고, conversion/fitting 대상로 취급한다

### Download policy
- official database download page를 통해 raw data 확보
- ingest 단계에서는 **read-only archive**로 먼저 보관
- direct Mitsuba import는 하지 않는다

### Storage target
- `data/utia/raw/`
- `data/utia/manifest/`
- `work/utia_conversion/`

### Mitsuba role
- `conversion_or_fitting_target`
- **not a first-pass integration target**

---

## 3.5 MERL BRDF database

### What it is
- 100 densely measured BRDFs
- sample code included
- access via Zenodo DOI

### Why we care
- historical baseline
- fitting / comparison / debugging용으로 여전히 유용

### Important caution
- polarization dataset 아님
- NIR dataset 아님
- first-class Mitsuba measured_polarized input으로 취급하지 않는다

### Download policy
- official MERL page -> Zenodo data
- sample code also archive

### Storage target
- `data/merl/raw/`
- `data/merl/manifest/`
- `work/merl_conversion/`

### Mitsuba role
- `conversion_or_fitting_target`

---

## 3.6 OpenSVBRDF

### What it is
- 1,000+ near-planar SVBRDFs
- 9 categories
- download via database portal
- 6 texture maps per sample:
  - diffuse albedo
  - specular albedo
  - anisotropic roughness
  - normal
  - tangent
  - transparency

### Why we care
- material count를 대규모로 늘릴 수 있음
- principled / GGX-style analytic pipeline에 연결 가능

### Important caution
- strict homogeneous BRDF 아님
- measured polarization 아님
- measured NIR BRDF 아님
- `specular albedo`가 `[0, 1]` 범위를 넘는 값도 존재하므로 project-level remapping policy 필요

### Download policy
- texture maps first
- neural representations and raw images are optional
- code repository optional

### Storage target
- `data/opensvbrdf/maps/`
- `data/opensvbrdf/meta/`
- `work/opensvbrdf_conversion/`

### Mitsuba role
- `svbrdf_asset_bank`
- **diversity expansion only**

---

## 4. Recommended implementation order

## Phase 0 — repository bootstrap

### Objective
프로젝트 구조와 manifest 체계를 먼저 고정한다.

### Required outputs
- directory tree
- dataset manifest schema
- Mitsuba variant policy
- rendering output naming convention

### Done criteria
- repo skeleton exists
- `datasets.yaml` exists
- `README_agent.md` / `IMPLEMENTATION_GUIDE.md` exists
- no dataset yet required

---

## Phase 1 — pBRDF baseline (must pass first)

### Objective
KAIST pBRDF를 이용해 Mitsuba 3의 `measured_polarized`가 실제로 동작하는 baseline을 만든다.

### Why this phase exists
hpBRDF는 patch가 필요하므로, 먼저 **공식 documented path**를 뚫어야 한다.

### Required tasks
1. Mitsuba 3 설치
2. `*_spectral_polarized` variant 선택
3. KAIST pBRDF material 1개 다운로드
4. `stokes` integrator로 EXR 출력
5. `S0/S1/S2/S3` 채널 확인

### Minimum acceptance test
- one `.pbsdf` loads
- one image renders
- one multichannel EXR written
- Stokes channels visible

### Canonical test materials
- `6_gold_inpainted.pbsdf` (metallic behavior)
- `7_fake_gold_inpainted.pbsdf`
- `15_white_silicone_inpainted.pbsdf`
- `1_spectralon_inpainted.pbsdf`

---

## Phase 2 — hpBRDF patched path (mainline)

### Objective
Mitsuba 3 source를 빌드하고 `measured_polarized.cpp` patch를 적용해 hpBRDF를 읽는다.

### Required tasks
1. Mitsuba 3 stable source clone (`--recursive`)
2. hpBRDF repo의 modified `measured_polarized.cpp` 확보
3. Mitsuba source tree에 patch 적용
4. `mitsuba.conf`에 spectral_polarized variants 활성화
5. rebuild
6. hpBRDF file 1개로 render test
7. fixed-wavelength and full-spectrum modes 비교

### Minimum acceptance test
- one `.hpbrdf` loads without format error
- one render completes
- one EXR with Stokes channels produced
- one NIR-adjacent wavelength test path documented

### Canonical test materials
- `Aluminum.hpbrdf`
- `Black glass.hpbrdf`
- `White smooth plastic.hpbrdf`
- `SUJ2.hpbrdf`

---

## Phase 3 — RGL spectral ingest

### Objective
RGL `_spec.bsdf` materials를 Mitsuba `measured`로 로딩하는 파이프라인 구축.

### Required tasks
1. representative isotropic material download
2. representative anisotropic material download
3. Mitsuba `measured` XML/Python loaders 작성
4. material metadata manifest 저장
5. NIR spectral workflow test

### Minimum acceptance test
- one isotropic and one anisotropic `.bsdf` load
- spectral render succeeds
- filenames and metadata normalized

### Canonical test material classes
- metal
- paper
- car paint
- fabric

---

## Phase 4 — conversion stubs (UTIA / MERL)

### Objective
UTIA와 MERL을 raw archive로 정리하고, 향후 변환 또는 fitting 파이프라인의 placeholder를 만든다.

### Required tasks
1. raw archive storage
2. per-material manifest generation
3. preview loader / reader setup
4. conversion TODO schema 정의

### Explicit non-goal
이 단계에서는 **direct Mitsuba integration을 완성하지 않아도 된다.**

---

## Phase 5 — OpenSVBRDF asset mapping

### Objective
OpenSVBRDF texture maps를 analytic material workflow로 투입할 수 있게 만든다.

### Required tasks
1. texture-map naming normalization
2. map loader
3. Mitsuba `principled` or custom mapping strategy 정의
4. clamp/remap policy for specular albedo
5. representative render tests

### Explicit non-goal
이 단계는 measured polarization 구현이 아니다.

---

## 5. Source-of-truth hierarchy

Agent는 data source를 아래 우선순위로 신뢰한다.

1. **Official dataset page / official code repo / official Mitsuba docs**
2. Dataset paper
3. Dataset hosting portal (Hugging Face, Zenodo, portal, etc.)
4. Our local manifest
5. Any inferred mapping / fitting result

In particular:
- polarization truth > spectral intensity truth > fitted approximation > SVBRDF analytic mapping

---

## 6. Download procedures

## 6.1 KAIST pBRDF download

### Method
- official KAIST dataset page 접속
- material별 `[mitsuba]` 다운로드
- optional: `[matlab]`도 같이 다운로드

### Required files
- `*_raw.pbsdf`
- `*_inpainted.pbsdf`
- `*_pbrdf.calib`
- optional `.mat`
- optional table / tensor helper files

### Post-download task
material manifest JSON/YAML 생성:
```yaml
dataset: pbrdf_2020
material_id: 6
material_name: gold
kind: measured_polarized
format: pbsdf
spectral_range_nm: [450, 650]
spectral_bands: 5
polarization: full_mueller
source_role: canonical_baseline
```

---

## 6.2 hpBRDF download

### Method
- official project page에서 Data -> Hugging Face dataset
- repo or files download
- official GitHub repo에서 `measured_polarized.cpp` 확보

### Required files
- `*.hpbrdf`
- patch source file
- local material manifest

### Post-download task
```yaml
dataset: hpbrdf_2025
material_name: aluminum
kind: measured_polarized
format: hpbrdf
spectral_range_nm: [414, 950]
spectral_bands: 68
polarization: full_mueller
source_role: canonical_nir_polarization
```

---

## 6.3 RGL material download

### Method
- official material database page에서 material 클릭
- spectral `.bsdf` (`*_spec.bsdf`) 우선 다운로드
- optional: RGB `.bsdf`

### Required files
- `*_spec.bsdf`
- optional raw data / preview info

### Post-download task
```yaml
dataset: rgl_material_db
material_name: cc_northern_aurora
kind: measured_spectral
format: bsdf
spectral_range_nm: [360, 1000]
polarization: none_measured
source_role: nir_material_bank
```

---

## 6.4 UTIA download

### Method
- official UTIA BRDF database download page
- raw archive first, conversion later

### Post-download task
- category tags 부여
- anisotropy flag 부여
- direct Mitsuba support 여부는 `unknown`으로 명시

Example:
```yaml
dataset: utia
material_name: placeholder_name
kind: raw_brdf
format: unknown
polarization: none_measured
source_role: conversion_target
category: fabric
```

---

## 6.5 MERL download

### Method
- official MERL page -> Zenodo DOI

### Post-download task
```yaml
dataset: merl
material_name: placeholder_name
kind: raw_brdf
format: merl
polarization: none_measured
source_role: conversion_target
```

---

## 6.6 OpenSVBRDF download

### Method
- database portal에서 texture maps 우선 다운로드
- neural representations / raw images는 optional

### Post-download task
```yaml
dataset: opensvbrdf
material_name: placeholder_name
kind: svbrdf_maps
format: texture_maps
polarization: none_measured
source_role: svbrdf_asset_bank
maps:
  - diffuse_albedo
  - specular_albedo
  - anisotropic_roughness
  - normal
  - tangent
  - transparency
```

---

## 7. Repository layout

권장 디렉토리 구조:

```text
project_root/
├── third_party/
│   ├── mitsuba3/
│   └── hpbrdf_patch/
├── data/
│   ├── pbrdf_2020/
│   │   ├── raw/
│   │   ├── mitsuba/
│   │   └── manifest/
│   ├── hpbrdf_2025/
│   │   ├── raw/
│   │   └── manifest/
│   ├── rgl_bsdf/
│   │   ├── spec/
│   │   ├── rgb/
│   │   └── manifest/
│   ├── utia/
│   │   ├── raw/
│   │   └── manifest/
│   ├── merl/
│   │   ├── raw/
│   │   └── manifest/
│   └── opensvbrdf/
│       ├── maps/
│       └── manifest/
├── tools/
│   ├── tekari/
│   └── preview/
├── configs/
│   ├── render/
│   ├── datasets/
│   └── variants/
├── scenes/
│   ├── smoke_tests/
│   ├── polarization/
│   └── nir/
├── scripts/
│   ├── download/
│   ├── manifest/
│   ├── convert/
│   ├── render/
│   └── inspect/
├── outputs/
│   ├── smoke_tests/
│   ├── polarization/
│   └── nir/
└── docs/
    └── IMPLEMENTATION_GUIDE.md
```

---

## 8. Mitsuba 3 environment policy

## 8.1 Quickstart policy

### For pBRDF baseline
`pip` 설치본의 polarized spectral variants로 먼저 시작할 수 있다.

Recommended Python default:
- `llvm_ad_spectral_polarized`

Fallback:
- `scalar_spectral_polarized`

### For hpBRDF
source build를 권장한다.  
이유:
- `measured_polarized.cpp` patch 필요

---

## 8.2 Build policy for source Mitsuba

### Canonical source branch
- `stable`

### Mandatory settings
- clone with `--recursive`
- enable at least:
  - `scalar_rgb`
  - one AD variant
  - at least one `*_spectral_polarized`

### Recommended enabled variants
```json
"enabled": [
  "scalar_rgb",
  "scalar_spectral_polarized",
  "llvm_ad_spectral_polarized"
]
```

### Notes
- too many variants increase compile time and memory usage
- keep variant set minimal

---

## 8.3 Patch policy for hpBRDF

### Required change
official hpBRDF repo가 제안한 수정대로,
`mitsuba3/src/bsdfs/measured_polarized.cpp`
에서 **fixed 5 visible wavelengths assumption**을 제거하고,
**dataset wavelength array length**에 맞게 dynamic allocation 하도록 수정한다.

### Agent behavior
- patch file를 그대로 vendoring 하거나
- our own patch script를 만든다

### Recommended approach
- patch source file를 `third_party/hpbrdf_patch/measured_polarized.cpp` 에 보관
- script로 copy
- build reproducibility 확보

---

## 9. Runtime rendering policy

## 9.1 Integrator policy

### For polarization outputs
반드시 `stokes` integrator 사용

Canonical XML pattern:
```xml
<integrator type="stokes">
    <integrator type="path"/>
</integrator>
```

### Rationale
이 구조여야 `S0/S1/S2/S3` multi-channel output을 EXR로 저장할 수 있다.

---

## 9.2 Output policy

### File format
- **OpenEXR multichannel**
- do not down-convert to PNG/JPG for canonical outputs

### Required outputs
- RGB view
- S0
- S1
- S2
- S3

### Naming
```text
{dataset}_{material}_{variant}_{scene}_{spp}spp.exr
```

Example:
```text
pbrdf2020_gold_llvm_ad_spectral_polarized_sphere_512spp.exr
```

---

## 9.3 Wavelength policy

### For pBRDF
- use documented `wavelength` parameter when needed
- valid range is tied to visible dataset workflow

### For hpBRDF
- prefer fixed wavelength experiments first
- then full-spectrum runs

### General rule
polarization analysis에서는 **fixed wavelength rendering을 first-class mode**로 유지한다.  
Spectral-to-RGB conversion 이후의 signed Stokes interpretation은 일부 응용에서 덜 이상적일 수 있기 때문이다.

---

## 10. Canonical scene snippets

## 10.1 pBRDF measured_polarized XML

```xml
<scene version="3.0.0">
    <integrator type="stokes">
        <integrator type="path"/>
    </integrator>

    <sensor type="perspective">
        <float name="fov" value="40"/>
        <sampler type="independent">
            <integer name="sample_count" value="512"/>
        </sampler>
        <film type="hdrfilm">
            <integer name="width" value="512"/>
            <integer name="height" value="512"/>
            <string name="file_format" value="openexr"/>
            <string name="pixel_format" value="rgb"/>
            <string name="component_format" value="float32"/>
        </film>
    </sensor>

    <shape type="sphere">
        <bsdf type="measured_polarized">
            <string name="filename" value="data/pbrdf_2020/mitsuba/6_gold_inpainted.pbsdf"/>
            <float name="alpha_sample" value="0.02"/>
        </bsdf>
    </shape>
</scene>
```

---

## 10.2 hpBRDF measured_polarized XML (after patch)

```xml
<scene version="3.0.0">
    <integrator type="stokes">
        <integrator type="path"/>
    </integrator>

    <sensor type="perspective">
        <float name="fov" value="40"/>
        <sampler type="independent">
            <integer name="sample_count" value="512"/>
        </sampler>
        <film type="hdrfilm">
            <integer name="width" value="512"/>
            <integer name="height" value="512"/>
            <string name="file_format" value="openexr"/>
            <string name="component_format" value="float32"/>
        </film>
    </sensor>

    <shape type="sphere">
        <bsdf type="measured_polarized">
            <string name="filename" value="data/hpbrdf_2025/raw/Aluminum.hpbrdf"/>
            <float name="alpha_sample" value="0.05"/>
        </bsdf>
    </shape>
</scene>
```

---

## 10.3 RGL measured XML

```xml
<scene version="3.0.0">
    <integrator type="path"/>

    <shape type="sphere">
        <bsdf type="measured">
            <string name="filename" value="data/rgl_bsdf/spec/cc_northern_aurora_spec.bsdf"/>
        </bsdf>
    </shape>
</scene>
```

---

## 10.4 Python rendering skeleton

```python
import mitsuba as mi

mi.set_variant('llvm_ad_spectral_polarized')

scene = mi.load_file('scenes/smoke_tests/pbrdf_gold.xml')
image = mi.render(scene, spp=512)

bitmap = mi.Bitmap(
    image,
    channel_names=['R', 'G', 'B'] + scene.integrator().aov_names()
)
bitmap.write('outputs/polarization/pbrdf_gold.exr')
```

---

## 11. Validation / smoke tests

## 11.1 pBRDF smoke test

### Input
- `6_gold_inpainted.pbsdf`

### Expected
- load succeeds
- render succeeds
- EXR written
- channel names include `S0`, `S1`, `S2`, `S3`

### Failure handling
- wrong variant -> switch to `*_spectral_polarized`
- file path issue -> fix manifest/path normalization
- no Stokes channels -> integrator wrapper missing

---

## 11.2 hpBRDF smoke test

### Input
- `Aluminum.hpbrdf`

### Expected
- patched build required
- load succeeds without 5-band assumption error
- render succeeds
- fixed-wavelength test documented

### Failure handling
- parser error -> patch not applied or rebuild stale
- runtime crash -> dataset file not correctly downloaded or path/permissions issue

---

## 11.3 RGL smoke test

### Input
- one isotropic `_spec.bsdf`
- one anisotropic `_spec.bsdf`

### Expected
- `measured` plugin load succeeds
- spectral render succeeds
- preview roughly consistent with Tekari / dataset preview

### Failure handling
- wrong variant -> use spectral variant
- wrong file type -> use `_spec.bsdf`, not unrelated raw file

---

## 12. Material strategy by research objective

## Objective A — "I need true polarization"
Use only:
- KAIST pBRDF
- hpBRDF

Priority:
1. pBRDF for implementation
2. hpBRDF for final experiments

---

## Objective B — "I need true polarization + NIR"
Use:
- hpBRDF only as canonical measured dataset

Optional supplement:
- analytic polarized BSDFs in Mitsuba
- but do not conflate them with measured hpBRDF

---

## Objective C — "I need many NIR materials"
Use:
1. RGL spectral database
2. hpBRDF (small but high-value)
3. optional analytic approximations

---

## Objective D — "I need as many materials as possible"
Use:
1. RGL
2. UTIA
3. MERL
4. OpenSVBRDF
5. plus pBRDF / hpBRDF for polarized anchor points

---

## 13. Conversion targets policy

## 13.1 UTIA
- retain original archive
- create metadata
- no direct import promise
- candidate downstream uses:
  - fitting to rough conductor / dielectric / pplastic
  - custom Python/C++ plugin
  - offline analysis of anisotropy statistics

## 13.2 MERL
- retain original archive
- candidate downstream uses:
  - baseline comparisons
  - model fitting
  - reflectance manifold experiments

## 13.3 OpenSVBRDF
- candidate downstream uses:
  - principled material authoring
  - map-based appearance variation
  - large-scale material variety benchmarks

---

## 14. Known caveats

1. **Polarization truth is scarce.**  
   Do not dilute the meaning of "polarized dataset".

2. **RGL paper samples may include fluorescence caveats.**  
   Some fluorescent paper materials may break energy conservation in renderings.

3. **OpenSVBRDF specular albedo may exceed 1.0.**  
   A project policy is required before mapping directly into a physically-based shader.

4. **hpBRDF requires source patching.**  
   Treat build reproducibility as a first-class deliverable.

5. **Fixed wavelength mode matters.**  
   Polarization analysis and signed Stokes interpretation are easier to reason about there.

---

## 15. Deliverables the agent should produce

## Deliverable D1 — dataset manifest
One unified machine-readable file:
- `configs/datasets/datasets.yaml`

Contents:
- dataset id
- local root
- source role
- format
- spectral range
- polarization support
- license note
- direct Mitsuba support yes/no
- conversion required yes/no

## Deliverable D2 — smoke-test scenes
At minimum:
- `scenes/smoke_tests/pbrdf_gold.xml`
- `scenes/smoke_tests/hpbrdf_aluminum.xml`
- `scenes/smoke_tests/rgl_isotropic.xml`

## Deliverable D3 — scripts
- `scripts/render/render_stokes.py`
- `scripts/manifest/build_manifest.py`
- `scripts/inspect/list_channels.py`
- `scripts/convert/README.md`

## Deliverable D4 — patched Mitsuba instructions
- one reproducible shell script or markdown file documenting:
  - clone
  - patch
  - configure
  - build
  - run

## Deliverable D5 — results
- one EXR per canonical smoke test
- one metadata summary per run

---

## 16. Agent task checklist

```yaml
tasks:
  - id: bootstrap_repo
    must: true
  - id: create_dataset_manifest_schema
    must: true
  - id: integrate_kaist_pbrdf
    must: true
  - id: render_pbrdf_stokes_exr
    must: true
  - id: patch_mitsuba_for_hpbrdf
    must: true
  - id: render_hpbrdf_stokes_exr
    must: true
  - id: integrate_rgl_measured_bsdf
    must: true
  - id: render_rgl_spectral_test
    must: true
  - id: archive_utia_raw
    must: true
  - id: archive_merl_raw
    must: true
  - id: ingest_opensvbrdf_maps
    should: true
  - id: implement_utia_conversion
    may: true
  - id: implement_merl_conversion
    may: true
```

---

## 17. Recommended first-week plan

### Day 1
- repo structure
- manifest schema
- Mitsuba quick test

### Day 2
- KAIST pBRDF material download
- first `measured_polarized` render
- EXR channel verification

### Day 3
- Mitsuba source build
- hpBRDF patch integration
- one hpBRDF render

### Day 4
- RGL spectral material ingest
- one isotropic + one anisotropic render

### Day 5
- UTIA / MERL archive
- OpenSVBRDF map ingest policy
- consolidated report

---

## 18. Stop conditions

Agent는 아래 상황에서 "integration complete for current phase"로 판단한다.

### Phase 1 stop condition
KAIST pBRDF material 1개가 `stokes` integrator와 함께 multichannel EXR로 안정적으로 렌더링된다.

### Phase 2 stop condition
hpBRDF material 1개가 patched Mitsuba 3에서 multichannel EXR로 안정적으로 렌더링된다.

### Phase 3 stop condition
RGL spectral `.bsdf` isotropic / anisotropic material 각각 1개씩 Mitsuba `measured`로 로드되어 렌더링된다.

---

## 19. References (official sources used to build this guide)

- Mitsuba 3 — Choosing variants  
  https://mitsuba.readthedocs.io/en/stable/src/key_topics/variants.html

- Mitsuba 3 — Compiling the system  
  https://mitsuba.readthedocs.io/en/stable/src/developer_guide/compiling.html

- Mitsuba 3 — Polarization  
  https://mitsuba.readthedocs.io/en/stable/src/key_topics/polarization.html

- Mitsuba 3 — Polarized rendering tutorial  
  https://mitsuba.readthedocs.io/en/stable/src/rendering/polarized_rendering.html

- Mitsuba 3 — BSDFs (`measured`, `measured_polarized`)  
  https://mitsuba.readthedocs.io/en/stable/src/generated/plugins_bsdfs.html

- KAIST pBRDF dataset page  
  https://vclab.kaist.ac.kr/siggraph2020/pbrdfdataset/kaistdataset.html

- RGL pBRDF publication page (Baek et al. 2020)  
  https://rgl.epfl.ch/publications/Baek2020Image

- hpBRDF paper (SIGGRAPH Asia 2025)  
  https://vclab.kaist.ac.kr/siggraphasia2025p3/SIGA2025-hpBRDF.pdf

- hpBRDF GitHub patch repo  
  https://github.com/yunseong0518/hpBRDF

- hpBRDF Hugging Face dataset  
  https://huggingface.co/datasets/yunseongmoon/Hyperspectral-Polarimetric-BRDF

- RGL material database  
  https://rgl.epfl.ch/pages/lab/material-database

- MERL BRDF database  
  https://www.merl.com/research/downloads/BRDF

- UTIA BRDF database  
  https://btf.utia.cas.cz/?brdf_dat_dwn=

- OpenSVBRDF  
  https://opensvbrdf.github.io/

---

## 20. Final instruction to the implementation agent

Start with **KAIST pBRDF**, not hpBRDF.  
Do not touch UTIA / MERL conversion before `measured_polarized` and `measured` baseline paths are both working.  
Treat **hpBRDF as the main research target**, **RGL as the NIR volume expansion layer**, and **UTIA / MERL / OpenSVBRDF as later-stage diversity sources**.
