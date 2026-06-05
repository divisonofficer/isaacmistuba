# Robomituba VLN/Navigation Multi-modal Dataset Readiness Report

작성일: 2026-05-26

## 결론

Robomituba는 현재 **단일 timestep / 단일 frame 기준의 고품질 multimodal observation sidecar renderer**로는 상당히 준비되어 있다. RGB, depth, polarization 파생물, active NIR-like proxy, reflective-surface depth corruption proxy를 RenderRequest -> ObservationBundleManifest 형태로 저장하는 계약과 구현이 있다.

하지만 질문의 목표인 **sequence 기반 navigation agent training dataset**, 특히 VLN 테스트용 episode dataset 생성 플랫폼으로는 아직 준비 완료 상태가 아니다. 핵심 누락은 navigation graph/traversable map, start-goal sampling, collision-free trajectory rollout, action/collision logging, language instruction, semantic/instance segmentation, LiDAR/point cloud, episode-level packaging이다.

요약하면:

- Render substrate readiness: 높음. 단, 현재 환경 검증은 Mitsuba variant 문제로 일부 테스트 실패.
- Multimodal optical research readiness: 중간 이상. NIR-like와 polarization은 지원되지만 representative scene 중심.
- VLN/navigation dataset readiness: 낮음~중간. episode generator 계층이 별도로 필요.

## 현재 구현 근거

주요 구현 지점:

- `README.md`: 현재 목표가 Isaac scene state를 source of truth로 두고 Mitsuba에서 `RGB / depth / polarization / NIR` 관측을 sidecar rendering하는 것이라고 명시한다.
- `modules/robomituba_bridge/src/robomituba_bridge/types.py`: `SceneState`, `CameraSpec`, `RenderRequest`, `RobotState`, `RenderArtifactManifest`, `ObservationBundleManifest`가 정의되어 있다.
- `modules/mitsuba_converter/src/mitsuba_converter/multimodal.py`: 지원 modality는 `rgb`, `depth`, `sensor_depth_approx`, `albedo`, light decomposition, `active_nir_intensity`, `polar_rgb_preview`, `dop`, `aolp`, `s1`, `s2`이다.
- `modules/mitsuba_converter/src/mitsuba_converter/observation_bridge.py`: RenderRequest를 camera별로 렌더링하고 frame 단위 observation bundle manifest를 쓴다.
- `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`: daemon/queue/Isaac session integration 경로가 있다.
- `apps/isaac_standalone` 및 `apps/isaac_extension`: USD stage snapshot export, shape map, Isaac current view/session capture를 지원한다.
- `modules/mitsuba_converter/src/mitsuba_converter/scene_floorplan.py`: top-down floor/shell/furniture/roof mask와 camera overlay 시각화는 있으나 navigation graph는 아니다.

## 요청 schema 대비 readiness

| 항목 | 상태 | 코멘트 |
|---|---:|---|
| `episode_id` | 미구현 | `job_id`, `request_id`, `extras.rollout_id`로 임시 표현은 가능하지만 episode contract는 없다. |
| `scene_id` | 준비됨 | `SceneState`, `SceneSnapshot`, `ObservationBundleManifest`에 존재. |
| `start_pose` | 부분 | `RobotState.base_pose`나 custom extras로 담을 수 있으나 episode-level 필드는 없다. |
| `goal_pose` | 미구현 | goal region/pose schema와 sampler 없음. |
| `natural_language_instruction` | 미구현 | template/LLM paraphrase pipeline 없음. |
| `trajectory` | 미구현 | path planner/rollout recorder 없음. |
| `actions` | 부분 | `RenderRequest.action_ref`만 있음. structured action sequence 없음. |
| `observations` | 부분 | frame/timestep observation bundle은 있음. episode sequence packaging은 없음. |
| `metadata` | 부분 | `extras`로 넣을 수 있으나 dataset schema로 고정되어 있지 않음. |

## Timestep observation 대비 readiness

| timestep 항목 | 상태 | 현재 구현/부족분 |
|---|---:|---|
| RGB image | 준비됨 | `rgb` modality. |
| Depth image | 준비됨 | `depth` AOV. |
| NIR-like image | 부분 준비 | `active_nir_intensity`는 camera-aligned assist light 기반 grayscale proxy. 물리적 NIR sensor 모델은 아님. |
| Polarization | 준비됨/부분 | `polar_rgb_preview`, `dop`, `aolp`, `s1`, `s2`. fallback logic 포함. 환경 variant 의존. |
| Hyperspectral | 부분/실험 | material catalog에는 hpBRDF/RGL spectral 정보가 있으나 dataset-wide hyperspectral image modality는 없다. |
| Semantic segmentation | 미구현 | renderer modality에 없음. floorplan category mask는 top-down helper일 뿐 camera semantic output이 아님. |
| Instance segmentation | 미구현 | mesh/instancer IDs는 snapshot에 있지만 per-pixel instance pass 없음. |
| LiDAR-like scan / point cloud | 미구현 | depth로 후처리하여 point cloud 생성 가능하지만 공식 modality/contract 없음. |
| Agent pose | 부분 준비 | `RobotState.base_pose`, `SceneSnapshot.robot_state` 가능. |
| Action | 부분 | `action_ref` 문자열만 있음. action payload/schema는 없음. |
| Collision flag | 미구현 | Isaac physics/collision event capture 없음. |
| glass/mirror/transparent object mask | 부분 | `sensor_depth_approx` 내부에서 `target_mask` raw channel을 만들지만 별도 public modality나 semantic class mask는 아님. |

## 실험 modality 조합 가능성

| 실험 | 가능 여부 | 코멘트 |
|---|---:|---|
| Baseline: RGB only | 가능 | 바로 가능. |
| +Depth: RGB + Depth | 가능 | 바로 가능. |
| +NIR-like: RGB + NIR-like | 가능/부분 | `active_nir_intensity` 사용. `AssistLightSpec` 필요. |
| +Segmentation: RGB + object/hazard mask | 미흡 | object/hazard camera mask modality가 필요. 현재 `target_mask`는 sensor depth 보조 내부 산출물. |
| +LiDAR-like: RGB + sparse depth/point cloud | 미흡 | depth 후처리로 만들 수 있지만 구현/manifest 없음. |
| Ours: RGB + NIR-like + Depth or hazard cue | 부분 가능 | RGB+Depth+NIR-like는 가능. hazard cue는 mask modality로 승격 필요. |

## 7단계 계획 대비 평가

### 1. Synthetic scene 생성

부분 준비. Isaac/Blender/USD scene authoring과 Mitsuba-side material override, curated material catalog, glass/dielectric/mirror-like preset은 있다. 그러나 procedural small indoor scene generator, category registry, goal region authoring contract는 없다.

필요 작업:

- `SceneObjectCategory`, `GoalRegion`, `HazardRegion`, `TransparentSurface` 같은 annotation schema 추가.
- small indoor scene fixture 또는 generator 추가.
- glass/mirror/transparent object를 dataset annotation으로 명시.

### 2. Navigation graph / traversable map 생성

미구현. `scene_floorplan.py`는 floorplan visualization과 rough category masks를 만들지만, navmesh/traversability, start-goal sampling, shortest path, collision-free rollout은 없다.

필요 작업:

- top-down occupancy/traversable grid 생성.
- nav graph 또는 navmesh builder.
- start/goal sampler.
- shortest path planner.
- Isaac physics 기반 collision validation 또는 geometric collision checker.

### 3. Multi-modal rendering

부분 준비. RGB/depth/NIR-like/polarization은 핵심 path가 있다. segmentation/LiDAR-like는 없다.

필요 작업:

- `semantic_segmentation`, `instance_segmentation`, `transparent_object_mask`, `hazard_mask` modality 추가.
- depth -> point cloud / sparse lidar scan converter 추가.
- NIR-like와 hyperspectral의 정의를 명확히 분리.
- sequence batch rendering API 추가.

### 4. Instruction generation

미구현. goal/category/route landmarks가 없어서 template instruction도 만들 수 없다.

필요 작업:

- scene annotation 기반 template generator.
- optional LLM paraphrase hook.
- instruction provenance와 human review status metadata.

### 5. Episode packaging

미구현/부분. `ObservationBundleManifest`는 timestep bundle에 가깝다. VLN-CE, LeRobot-like, custom JSON 중 하나로 episode schema를 확정해야 한다.

추천:

- 먼저 custom JSONL/JSON episode format을 정의한다.
- 각 timestep은 기존 ObservationBundleManifest를 참조한다.
- 이후 VLN-CE/LeRobot export adapter를 별도로 만든다.

### 6. Fine-tuning

미구현. 이 repo에는 training dataloader/model fine-tuning pipeline이 없다.

추천:

- 이 repo는 dataset generation/export까지만 책임지고, training은 별도 repo 또는 `experiments/`로 분리.
- baseline RGB-only와 multimodal variant가 같은 episode split을 참조하도록 manifest 설계.

### 7. Evaluation

미구현. held-out synthetic scene split, real small validation scene split, SPL/success/collision metrics가 없다.

필요 작업:

- train/val/test scene split metadata.
- evaluator input schema.
- success, SPL, collision rate, path length, modality ablation metrics.

## 가장 큰 리스크

1. Episode abstraction 부재

현재 시스템은 `frame_id` 중심이다. VLN/navigation dataset은 `episode_id -> timesteps[] -> observations/actions` 구조가 중심이므로 새 contract가 필요하다.

2. Navigation/physics loop 부재

Robomituba는 renderer bridge에 집중되어 있다. start-goal sampling, planner, rollout, collision flag는 Isaac/geometry 쪽에서 새로 붙여야 한다.

3. Segmentation/LiDAR modality 부재

요청 실험의 핵심 비교군인 segmentation/hazard mask/LiDAR-like가 아직 공식 modality가 아니다.

4. NIR/hyperspectral 의미 정리 필요

`active_nir_intensity`는 NIR-like proxy다. hpBRDF/RGL material catalog와 spectral variant 계획은 있지만, camera hyperspectral cube modality와 dataset contract는 없다.

5. 현재 환경 검증 이슈

다음 명령을 실행했을 때 24개 중 7개가 실패했다.

```bash
python3 -m unittest tests.contract.test_multimodal_api tests.contract.test_observation_bridge tests.contract.test_bridge_contract
```

실패 원인은 `MitsubaVariantUnavailable: Mitsuba is not importable or reports no compiled variants.`였다. 즉 현재 셸 환경에서는 Mitsuba variant가 잡히지 않아 rendering contract smoke가 green이 아니다. `docs/2026-05-19_phase_r_environment_handoff.md`에는 별도 `mitsuba_optix7` conda env 및 OptiX/variant 제약이 정리되어 있다.

## 권장 MVP 범위

VLN 전체를 바로 목표로 잡기보다 다음 순서가 현실적이다.

1. `EpisodeManifest` contract 추가

필드:

- `episode_id`
- `scene_id`
- `split`
- `start_pose`
- `goal_pose`
- `goal_region`
- `natural_language_instruction`
- `trajectory`
- `actions`
- `timesteps[]`
- `metadata`

각 timestep:

- `timestep_index`
- `timestamp`
- `agent_pose`
- `action`
- `collision`
- `observation_bundle_ref`

2. 최소 modality MVP

첫 MVP는 다음만 대상으로 한다.

- `rgb`
- `depth`
- `active_nir_intensity`
- `transparent_object_mask` 또는 `hazard_mask`
- `agent_pose`
- `action`
- `collision`

LiDAR-like와 semantic/instance segmentation은 2차로 둔다.

3. Navigation MVP

- small indoor scene 1-3개.
- manually annotated traversable map + goal regions.
- A* shortest path.
- simple discrete actions: `move_forward`, `turn_left`, `turn_right`, `stop`.
- collision-free planned trajectory를 우선 저장하고, Isaac physics rollout은 2차 검증으로 둔다.

4. Dataset export MVP

처음에는 custom JSON으로 고정한다.

예상 구조:

```json
{
  "episode_id": "episode-000001",
  "scene_id": "small_indoor_001",
  "start_pose": [0, 0, 0],
  "goal_pose": [3, 0, 2],
  "natural_language_instruction": "Go to the glass door near the table.",
  "trajectory": [],
  "actions": [],
  "timesteps": [
    {
      "timestep": 0,
      "agent_pose": [],
      "action": "move_forward",
      "collision": false,
      "observation_bundle_ref": "out/bridge_jobs/job-.../observations/frame_0000/manifest.json"
    }
  ],
  "metadata": {
    "modalities": ["rgb", "depth", "active_nir_intensity", "transparent_object_mask"]
  }
}
```

## 최종 판단

Robomituba는 **navigation dataset generator의 rendering backend로 쓸 준비는 되어가고 있지만, dataset generator 자체는 아니다.**

질문에 적은 계획을 실행하려면 기존 rendering/bridge를 유지하면서 다음 새 모듈을 추가하는 것이 맞다.

- `navigation_dataset/episode_schema.py`
- `navigation_dataset/scene_annotations.py`
- `navigation_dataset/traversability.py`
- `navigation_dataset/planner.py`
- `navigation_dataset/rollout.py`
- `navigation_dataset/instruction_templates.py`
- `navigation_dataset/exporters/custom_json.py`

최소 논문/실험용 MVP까지는, 기존 rendering stack을 재사용하면 **새 episode/navigation 계층 구현에 집중해서 약 2-4주 규모**로 볼 수 있다. 단, semantic/instance segmentation과 LiDAR-like까지 안정화하려면 별도 2차 작업이 필요하다.
