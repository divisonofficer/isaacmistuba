"""rooms.json for the apartment floor scenes P3-P6 (user 2026-10-24; hand-built from the brochure sheets' briefs until the Codex clean plans arrive, then refined).
A tower floor: one common corridor along y = 0-2 (entrance wall y = 0), a lift + stair core, units stacked side by side above it (y 2-14), alternate units mirrored.
Unit template (width w: 11 m = the 110 m2 class, 9 m = 84 m2, 10.5 m = 99 m2), x measured from the unit's corridor-side left corner:
  entrance (shoe room, 'closet') -> internal hall -> kitchen / bed2 / bath; hall opens to the living room on the south facade; dining open between kitchen and living; master bedroom off the living room
  (+ master bath and walk-in for w >= 10.5); utility / laundry behind the bath.
Run: python apt_floor_rooms.py  (writes data/venue_refs/floor_plans_v3/APT1..APT4/rooms.json)."""
import json
from pathlib import Path

OUT = Path("/jarvis/project/robomituba/data/venue_refs/floor_plans_v3")


def unit(p, x0, w, mirror):
    s = w / 9.0 if w < 10 else w / 11.0
    big = w >= 10.5
    def X(a, b):                                    # template x in a 11 m unit (scaled), mirrored if asked
        a, b = a * w / 11.0, b * w / 11.0
        return (x0 + w - b, x0 + w - a) if mirror else (x0 + a, x0 + b)
    R = []
    def room(n, t, xa, xb, y0, y1, doors=(), opens=()):
        a, b = X(xa, xb); R.append({"name": f"{p}_{n}", "type": t, "rect": [round(a, 2), y0, round(b, 2), y1], "doors_to": [f"{p}_{d}" if not d.startswith("!") else d[1:] for d in doors], "open_to": [f"{p}_{o}" for o in opens]})
    room("entrance", "closet", 4.0, 6.5, 2, 4, doors=("!corridor", "hall"))
    room("hall", "hallway", 4.0, 6.5, 4, 8, doors=("bath", "bed2"), opens=("kitchen", "living"))
    room("bath", "bathroom", 6.5, 9.0, 2, 4.5, doors=("entrance", "utility"))
    room("utility", "utility", 9.0, 11.0, 2, 4.5, doors=("bath",))
    room("bed2", "bedroom", 6.5, 11.0, 4.5, 8, doors=("hall",))
    room("kitchen", "kitchen", 0.0, 4.0, 2, 6, opens=("hall", "dining"))
    room("dining", "dining-room", 0.0, 4.0, 6, 9, opens=("kitchen", "living"))
    room("living", "living-room", 4.0, 11.0, 8, 14, doors=("master",), opens=("hall", "dining"))
    if big:
        room("master", "bedroom", 0.0, 4.0, 11, 14, doors=("living", "master_bath", "wardrobe"))
        room("master_bath", "bathroom", 0.0, 2.0, 9, 11, doors=("master",))
        room("wardrobe", "closet", 2.0, 4.0, 9, 11, doors=("master",))
    else:
        room("master", "bedroom", 0.0, 4.0, 9, 14, doors=("living",))
    return R


def floor(name, units, core_after, h=None):
    rooms, x = [], 0.0
    for i, (w, label) in enumerate(units):
        if i == core_after:
            rooms += [{"name": "elevator_hall", "type": "hallway", "rect": [x, 2, x + 5, 7], "doors_to": [], "open_to": ["corridor"]},
                      {"name": "stair", "type": "utility", "rect": [x, 7, x + 5, 14], "doors_to": ["elevator_hall"], "open_to": []}]
            core_x = x + 2.5; x += 5
        rooms += unit(label, x, w, mirror=bool(i % 2)); x += w
    H = 14
    W = round(x, 2)
    rooms.insert(0, {"name": "corridor", "type": "hallway", "rect": [0, 0, W, 2], "doors_to": [r["name"] for r in rooms if r["name"].endswith("_entrance")], "open_to": ["elevator_hall"]})
    d = {"scene": name, "size_m": [W, H], "entrance_x": core_x, "coordinate_frame": "x east, y north; y = 0 common corridor front wall, units face south (y = 14)", "rooms": rooms,
         "provenance": "hand-built template (apt_floor_rooms.py), pending the Codex clean plan"}
    (OUT / name).mkdir(parents=True, exist_ok=True)
    (OUT / name / "rooms.json").write_text(json.dumps(d, indent=1))
    return d


if __name__ == "__main__":
    for nm, units, core in (("APT1", [(11, "a"), (9, "b")], 1),                        # P3 apartment_floor_01: a 110 m2 + an 84 m2 unit
                            ("APT2", [(9, "a"), (9, "b"), (9, "c")], 1),               # P4 apartment_floor_02: three 84 m2 type-A units
                            ("APT3", [(9, "a"), (10.5, "b")], 1),                      # P5 apartment_floor_03: an 84 m2 + a 99 m2 unit
                            ("APT4", [(9, "a"), (9, "b"), (9, "c"), (9, "d")], 2)):    # P6 apartment_floor_04: four mirrored 84.98 m2 units
        d = floor(nm, units, core); print(nm, d["size_m"], len(d["rooms"]))
