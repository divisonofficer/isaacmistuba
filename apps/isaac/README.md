# apps/isaac/

Isaac Sim 인터랙션 전용 스크립트.

## 파일

| 파일 | 역할 | 호출 주체 |
|---|---|---|
| `capture_current_view.py` | Isaac Sim 의 현재 viewport 카메라를 robomituba 의 RenderRequest 로 캡처해서 데몬에 제출. WSL ↔ Windows UNC 경로 변환 포함. | `modules/mitsuba_converter/render_daemon.py` 가 [render_daemon.py:16689] 에서 직접 `python ... apps/isaac/capture_current_view.py` 로 실행. |
| `script_editor_shim.py` | Isaac Sim 의 Script Editor 에서 `import robomituba_isaac` 형태로 단일 파일 import 하기 위한 facade. | Isaac Sim 사용자가 수동 import. |

## 관련 디렉터리

- `../isaac_extension/` — Isaac Sim 의 UI 패널 확장 (별개 패키지).
- `../isaac_standalone/` — Isaac Sim 의 headless export 스크립트.

## 이전 위치

이 두 스크립트는 원래 `apps/` 루트에 있었음 (`isaac_capture_current_view_request.py`, `robomituba_isaac.py`). 2026-06-10 정리에서 Isaac 관련 묶음으로 분리. render_daemon 의 path 참조도 같이 갱신됨.
