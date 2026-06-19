# apps/migrations/

**한 번만 적용하면 끝나는 마이그레이션 / fix-up 스크립트.** 한 시점의 데이터 결함을 보수하는 용도라 일반 도구와는 다른 성질.

## 파일

| 파일 | 적용 시점 | 무엇을 고치나 |
|---|---|---|
| `fix_authoring_map_metadata.py` | Phase 1 (editor mesh display 복원) | `metadata.asset_source_path` / `metadata.usd_ref` 가 비어있는 authoring object 에 USD prim path 를 채워, MapEditor3D 가 `/prim-mesh` endpoint 로 실제 mesh 를 가져올 수 있게 한다. |
| `rerender_optical_nav_grid.py` | `measured_polarized_rgb` BSDF 컴파일 직후 | 옛 3-pass channel-split fallback 으로 생성된 grid frame (luminance collapsed → grey) 을 새 single-pass plugin 으로 재렌더. in-process loop 라 Mitsuba scene cache 유지. |

## 운영 규칙

- 적용 후 같은 데이터셋에 다시 돌릴 필요 없음 (idempotent 이거나 한 번만 적용).
- 새 scene 에 대해 같은 fix 가 또 필요해지면 그건 일반 도구로 승격할 신호 — `apps/` 루트로 옮기고 시그니처 정리.
- 보존 이유: 데이터셋 마이그레이션 이력의 trace + 다른 환경에서 같은 보수가 필요할 때 reference.

## 이전 위치

원래 `apps/` 루트. 2026-06-10 정리에서 분리.
