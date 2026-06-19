# apps/scenes/

**한 scene 을 만들기 위해 작성된 install / import 스크립트.** 하드코딩된 좌표·prim path·재질 매핑이 있어서 일반 도구로 분류되지 않음.

## 파일

| 파일 | 만들어내는 scene | 한 줄 설명 |
|---|---|---|
| `install_cglab_conference_room.py` | `cglab_conference_room` | CG-Lab 회의실 — 유리벽 segment / 기둥 좌표 cm 단위로 직접 인코딩, AuthoringMap (meters) 생성 → compile → sync → materialize. |
| `install_shared_office_sample.py` | `shared_office_floor` | 공유 오피스 한 층 seed scene. shell + asset placeholder. |
| `import_moorelane_kitchen.py` | `moorelane_kitchen_001` | `office_lobby_001` authoring_map 의 `/ROOT/Kitchen/*` prim 만 추출해서 새 scene 생성. |

## 새 scene 추가 패턴

```
apps/scenes/install_<scene_id>.py     # 측정/관찰 데이터 → AuthoringMap → compile → sync
apps/scenes/import_<source>_<area>.py # 기존 USD/scene 의 일부 prim 추출 → 새 scene
```

각 스크립트는 자기 완결적 — 다른 scene 의 코드를 import 하지 않음. 일반 install pipeline 으로 추상화될 만큼 패턴이 안정화되면 모듈로 옮길 것.

## 이전 위치

원래 `apps/` 루트에 있었음. 2026-06-10 정리에서 일반 도구와 분리.
