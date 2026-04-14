# isaac_standalone

Windows Isaac Sim에서 stage를 읽고 `out/bridge_jobs/<job_id>`를 생성하는 standalone 진입점 모음.

현재 범위:

- 현재 stage 또는 지정 USD를 읽기
- stage 요약 확인
- bridge job 생성
- snapshot JSON과 exported USD 저장

현재 범위 밖:

- Isaac viewport renderer 교체
- Mitsuba 호출
- 실시간 bi-directional sync

예시:

```bash
python.bat apps/isaac_standalone/inspect_stage.py
python.bat apps/isaac_standalone/export_job.py --scene-id glass_hallway --frame-id frame_0001
python.bat apps/isaac_standalone/export_snapshot.py --usd path/to/stage.usda --snapshot-dir out/manual_snapshot
```
