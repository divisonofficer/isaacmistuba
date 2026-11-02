"""One feedback round for one room, as a subprocess of the Blender realizer (the anthropic SDK lives in the system python).

    python -m room_planner.revise REQ.json OUT.json      (run from tools/infinigen)

REQ: {"room": <room payload without "_" keys>, "plan": <plan>, "report": <realizer report>, "seed": N}; OUT: the revised plan.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from room_planner import client  # noqa: E402

req = json.loads(Path(sys.argv[1]).read_text())
plan = client.revise_room(req["room"], req["plan"], req["report"], req.get("seed", 0))
Path(sys.argv[2]).write_text(json.dumps(plan, indent=1, ensure_ascii=False))
print("REVISED", len(plan.get("furniture", [])), "furniture", flush=True)
