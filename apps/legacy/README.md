# apps/legacy/

**OpticalNav 데이터셋 / render daemon 도입 이전에 쓰던 옛 카메라 sweep 워크플로.** 현 시점에서는 사용 안 되지만 일부 코드는 참고/디버그 시 유용해서 보존.

## 파일

| 파일 | 옛 역할 | 무엇이 대체하나 |
|---|---|---|
| `render_candidate_cameras.py` | 3D 공간에서 후보 카메라 위치 자동 생성 + 후보별 RGB 렌더 (선별용) | `apps/opticalnav.py` 의 viewpoint graph 자동 sampling. |
| `render_curated_multimodal.py` | 큐레이션된 카메라 목록으로 multi-modal 렌더 | webui editor 의 episode-nodes / graph-sweep + render daemon. |
| `render_selected_cameras_multimodal.py` | `--camera_ids` 로 명시한 카메라들 multi-modal 렌더 (스탠드얼론 entry) | render daemon 의 `/render` 경로 + RenderRequest. |
| `make_selected_camera_sheets.py` | 선택 카메라들 HTML 시트 / 메타데이터 묶음 | webui 의 inspector / RailPathsTab. |
| `render_reflective_island_frontal_demo.py` | 반사 물체 다중 뷰 렌더 demo | 별도 유스케이스 없음. |

## 내부 의존

`render_candidate_cameras.py` 가 `render_curated_multimodal` 의 `save_rgb_preview` / `write_json` 을 import — **같은 디렉터리에 묶여있으므로 그대로 동작**. 다른 곳에서 import 하지 않음.

## 운영 규칙

- 새 기능 추가 X.
- 버그 fix 도 가급적 안 함 (참고용으로만).
- 명백히 obsolete 한 게 확인되면 삭제 검토.

## 이전 위치

원래 `apps/` 루트. 2026-06-10 정리에서 일반 도구와 분리 (OpticalNav 흐름이 정착하면서 옛 카메라 sweep 흐름은 noise 가 됐음).
