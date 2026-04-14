# robomituba_bridge

Isaac Sim authoring side와 Mitsuba rendering side가 공유하는 bridge contract 패키지.

이 패키지는 다음만 담당한다.

- job manifest 형식
- scene snapshot 타입
- repo-relative path 규칙
- snapshot / manifest read-write 유틸리티
- renderer와 authoring 양쪽에서 재사용 가능한 재질 분류 보조 로직

이 패키지에는 Isaac Sim 전용 import와 Mitsuba 전용 import를 넣지 않는다.
