"""Plan every room of a scene with Claude.

    python -m room_planner.plan_scene rooms.json --out plans.json [--seed N] [--types living-room,bedroom,dining-room] [--dry-run]

Needs ANTHROPIC_API_KEY for a live call; --dry-run prints the first request instead. Plans are cached (client.CACHE).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from room_planner import client  # noqa: E402

PLANNED = ("living-room", "bedroom", "dining-room", "warehouse", "garage", "office", "open-office", "meeting-room", "break-room", "cafe", "grocery",
           "clinic-reception", "exam-room", "dental-room", "physio-room", "convenience", "boutique", "pharmacy")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rooms", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--types", default=",".join(PLANNED))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--venue", help="relabel every room as this type (a single-room layout used as a cafe / grocery store)")
    ap.add_argument("--style", help="venue style preset (room_planner/styles.py), e.g. cafe: nordic_bakery, industrial_brick")
    ap.add_argument("--reference", type=Path, help="venue spec from room_planner.reference: its brief, must-haves and images steer the plan")
    ap.add_argument("--room-venues", type=Path, help="{room name: venue} json: a multi-room floor whose rooms take venue rules (clinic, "
                                                     "cafe); rooms not in the map keep their own type (user 2026-10-16: floor scenes)")
    a = ap.parse_args()
    types = set(a.types.split(","))
    doc = json.loads(a.rooms.read_text())
    spec = json.loads(a.reference.read_text()) if a.reference else None
    images = spec.get("images") if spec else None  # hand-written briefs carry no images
    out = {"scene": doc["scene"], "model": client.MODEL, "prompt_version": client.PROMPT_VERSION, "seed": a.seed, "rooms": {},
           "venue": a.venue, "style": a.style, "style_spec": spec}
    room_venues = json.loads(a.room_venues.read_text()) if a.room_venues else {}
    out["room_venues"] = room_venues
    for room in doc["rooms"]:
        if a.venue:
            room = {**room, "type": a.venue}
        if room.get("id") in room_venues or room.get("name") in room_venues:
            room = {**room, "type": room_venues.get(room.get("id")) or room_venues[room.get("name")]}
        if a.style:
            from room_planner import styles
            room = {**room, "style": styles.get(a.venue, a.style)["brief"]}
        if a.reference and (len(doc["rooms"]) == 1 or not spec.get("venue") or room["type"] == spec["venue"]):   # on a floor the kit's
            # brief and must-haves belong to its own venue's room, office floors too (floor C r3: the open-office brief made the pantry a
            # hot-desk area -- 1 of 15 items fit, a bare room)
            room = {**room, "style": spec["brief"], "must_have": spec.get("must_have", []), "reference_ids": spec.get("reference_ids", [])}
        prog = ((spec or {}).get("room_program") or {}).get(room.get("id"))          # a kit's PER-ROOM program (P2: one reference photo + brief + must-haves per room) replaces the whole-apartment brief
        room_images = images
        if prog:
            room = {**room, "style": prog["brief"], "must_have": prog.get("must_have", []), "reference_ids": prog.get("reference_ids", [])}
            room_images = [prog["image"]] if prog.get("image") else images
            # to its own venue's room (floor G: the café brief put a coffee bar and tables in the storage room, reception's in exam rooms)
        if prog and prog.get("layout"):                          # kit room_program[id]["layout"] = a layout.json from the reference floor plan: the room is FIXED, furnished only from it (realize._run_layout)
            out["rooms"][room["id"]] = {"plan": {"occupant": "customers and staff", "tidiness": 0.8, "lived_in": list(prog.get("lived_in", [])), "furniture": [], "fixed": True, "layout": prog["layout"], "layout_entrance_u": prog.get("layout_entrance_u"), "auto_allow": list(prog.get("auto_allow", []))}, "room": room}
            continue
        if prog and prog.get("fixed_furniture") and room["type"] in ("break-room", "warehouse"):
            # a kit's FIXED program wins over the venue type: floors G / H map the kitchen cell to venue 'break-room' and the utility cell to 'warehouse' (room_venues), so their room_program
            # fixed_furniture (stainless kitchen, wire racks, water heater, mop sink) never reached the fixed branches below and the LLM planned a pantry / retail stockroom instead (H r54)
            out["rooms"][room["id"]] = {"plan": {"occupant": "staff", "tidiness": 0.8, "lived_in": list(prog.get("lived_in", [])), "furniture": list(prog["fixed_furniture"]), "fixed": True}, "room": room}
            continue
        home_ = any(r_["type"] == "bedroom" for r_ in doc["rooms"])      # an apartment (P2 r7 LAY-02: closet and utility completely bare): its service rooms get the same fixed fit-out as a floor's
        prog_floor_ = bool((spec or {}).get("room_program"))                  # a floor kit with a room_program (N2) has no venue map but still wants its service / corridor rooms planned as fixed rooms
        if (room_venues or home_ or prog_floor_) and room["type"] in ("utility", "closet") and room["id"] not in room_venues:
            # floors: service rooms no venue covers get a fixed fit-out (floor E: the sterilisation room rendered empty)
            clinic = any(v in ("clinic-reception", "exam-room", "dental-room", "physio-room") for v in room_venues.values())
            def free_(w_):                                   # the longest unbroken stretch of a wall
                cuts = sorted((b[0], b[1]) for b in w_.get("blocked", []))
                best, s0 = 0.0, 0.0
                for b0, b1 in cuts + [(w_["length"], w_["length"])]:
                    best = max(best, b0 - s0); s0 = max(s0, b1)
                return best
            wl = sorted(room.get("walls", []), key=free_, reverse=True)
            w_rack, w_run = (wl[0]["id"] if wl else None), (wl[1]["id"] if len(wl) > 1 else None)
            n_rack = max(1, min(4, int((free_(wl[0]) - 0.3) / 1.27))) if wl else 2
            furn = ([{"id": "run", "category": "medical_cabinet", "relation": "against_wall", **({"wall": w_run} if w_run else {})},
                     {"id": "racks", "category": "supply_shelf", "relation": "row", **({"wall": w_rack} if w_rack else {}), "count": n_rack}]
                    # shelving as a row on the longest clear wall: the sink run took that wall first and the shelves found door-broken
                    # walls, 1 of 4 placed (floor E3 r20: 'one rack', completeness 4-5, 3 of 3) -- a clinical supply room: a sink run + white supply
                    # shelving (a sterilisation room never read as one: autoclaves seen as 'a washer and dryer' / 'microwaves', E3 r12-r16)
                    if clinic and room["type"] == "utility" else
                    [{"id": "lockers", "category": "locker", "relation": "against_wall", "count": 2},
                     {"id": "bench", "category": "changing_bench", "relation": "in_front_of", "target": "lockers", "gap_m": 0.6},
                     {"id": "mirror", "category": "mirror", "relation": "against_wall", "away_from": "lockers"}]
                    if room["type"] == "closet" and not home_ else
                    [{"id": "racks", "category": "storage_rack", "relation": "against_wall", "count": 2}])
            stock = ([{"category": "storage_bin" if furn[0]["id"] == "run" else "cardboard_box", "on": "racks", "fill": True}] +
                     ([{"category": "cardboard_box", "on": "racks", "fill": True}] if furn[0]["id"] == "run" else []) +   # topped up:
                     # bins alone left ~6 items a unit, 'sparse coloured blocks' (floor E3 r19: comp 5, use 4, 3 of 3)
                     ([{"category": "glove_box", "on": "run"}, {"category": "glove_box", "on": "run"}] if furn[0]["id"] == "run" else [])
                     # bins and glove boxes, not plain cartons: 'a generic storeroom, nothing clinical' (floor E3 r17, comp 4-5, 3 of 3)
                     if any(f["id"] == "racks" for f in furn) else   # every level
                                                                 # (floor E3 r3: one box tried, 'no fit', a bare rack)
                     [{"category": "towel_stack", "on": "bench"}, {"category": "laundry_basket", "on": "floor"}]   # a changing room in use
                     if furn[0]["id"] == "lockers" else [])                                                       # (floor F r2: use 3, 3 of 3)
            prog_ = (((spec or {}).get("room_program") or {}).get(room["id"]) or {})                      # a kit's room_program gives a service-type room its own fixed fit-out (N2: laboratories are 'utility' cells)
            if prog_.get("fixed_furniture"):
                furn = list(prog_["fixed_furniture"]); stock = list(prog_.get("lived_in", []))
            out["rooms"][room["id"]] = {"plan": {"occupant": "staff", "tidiness": 0.8, "lived_in": stock, "furniture": furn, "fixed": True}, "room": room}
            continue
        if home_ and room["type"] == "balcony" and "balcony" not in types:          # P2 ref varanda_01: a round table, four teal chairs, plants along the balustrade
            furn = [{"id": "bt", "category": "balcony_table", "relation": "center"}, {"id": "bc", "category": "balcony_chair", "relation": "around", "target": "bt", "count": 4},
                    {"id": "bp", "category": "floor_plant", "relation": "against_wall", "count": 3}]
            out["rooms"][room["id"]] = {"plan": {"occupant": "residents", "tidiness": 0.8, "lived_in": [], "furniture": furn, "fixed": True}, "room": room}
            continue
        if room["type"] == "hallway" and (room_venues or prog_floor_):
            # floors: a corridor gets wall fittings only -- notices, a clock, sanitiser (floors D3/E3/F3: 'a bare tube', use 3-4, 3 of 3)
            fixed_ = list((((spec or {}).get("room_program") or {}).get(room["id"]) or {}).get("fixed_furniture", []))   # a kit's room_program may give a corridor-type room its own fixed pieces (S28 floor: elevator doors in the lobby)
            out["rooms"][room["id"]] = {"plan": {"occupant": "staff and visitors", "tidiness": 0.8, "lived_in": [], "furniture": fixed_,
                                                 "fixed": True}, "room": room}
            continue
        if room["type"] == "restroom":
            # floors: a restroom gets fixed sanitary ware, no LLM call (the solver that would fit it is off on floors, 2026-10-16)
            # always one open WC: the stall factory's panels read as 'loose boards at odd angles' in every floor (A, B, D3, E3, J, 3/3
            # each), while the open WC + basin restrooms scored 7 on function; a large room gets a second basin, not a second stall
            n_basin = 1                                         # one basin + mirror (floor D3 r6: two basins and two mirrors, 3 of 3)
            plan = {"occupant": "staff and visitors", "tidiness": 0.8, "fixed": True,
                    "lived_in": [{"category": "sanitizer", "on": "basin"}, {"category": "paper_towel", "on": "basin"}],   # soap + towels at the
                    # basin (floors G/H r14-r16: 'no soap'; H r26: 'no paper, nothing used')
                    "furniture": [{"id": "wc", "category": "wc", "relation": "against_wall", "avoid_windows": True},
                                  {"id": "basin", "category": "wash_basin", "relation": "against_wall", "near_to": "wc", "count": n_basin}]}
            # (an open WC with its basin on the far wall read as 'a toilet alone in an empty room' -- floor A2 r4; fixtures go together)
            clinic = any(v in ("clinic-reception", "exam-room", "dental-room", "physio-room") for v in room_venues.values())
            # (no lockers + bench in a big work-floor washroom any more: beside an open WC they read as 'a changing room with a toilet
            # dropped in', floor J r18-r21, 3 of 3 each -- the urinal pair below fills the room instead)
            cafe_fl = any(v == "cafe" for v in room_venues.values())
            if room_venues and not clinic and room.get("area_m2", 0) >= 10 and (str(room.get("id", "")).endswith("/1") or
                                                                                (not cafe_fl and room.get("area_m2", 0) >= 12)):   # 12, not 18: a
                # work floor's 12-18 m2 staff WC with one open toilet read as 'a converted room' (floor B r11, use 3-4, 3 of 3)
                # also a work floor's one big staff restroom: 'one WC in a room for three cubicles' (floor B r10, 3 of 3)
                plan["furniture"][0] = {**plan["furniture"][0], "category": "toilet", "relation": "corner"}   # a cubicle in a corner: off
                # one wall it stood 'free in the room' (floor H r43 WC1 layout 5, 3 of 3)
                plan["furniture"][1] = {**plan["furniture"][1], "near_to": None, "away_from": "wc"}   # the basin faces the cubicle: near
                # it, it took the 0.45 m gap beside the stall and read as 'a basin inside the stall' (floor J r25, 3 of 3)   # with urinals the WC is a cubicle: open beside
                # them it read as 'a toilet standing in the open next to the urinals' (floor J r23, 3 of 3)
                plan["furniture"] += [{"id": "urinals", "category": "urinal", "relation": "against_wall", "away_from": "wc",
                                       "avoid_windows": True}]   # not under the street window (floor H r42, 3 of 3)   # the second
                # restroom is the gents': two urinals fill its bare far wall and the pair stop being copies (floor H r31, 3 of 3)
            if room_venues and any(v in ("cafe",) for v in room_venues.values()):   # a café WC's potted plant on the floor (floor G r29:
                plan["lived_in"] += [{"category": "small_plant", "on": "floor"}]      # 'only the roll and soap show use', use 6, 2 of 3)
            if (spec or {}).get("restroom_style") == "oak_tile_double":    # B: two cubicles + two basins on a long oak vanity (two oak vanities side by side)
                plan["furniture"] = [{"id": "wc", "category": "wc_cubicle", "relation": "corner", "avoid_windows": True, "count": 2},
                                     {"id": "basin", "category": "oak_vanity_long", "relation": "against_wall", "away_from": "wc", "avoid_windows": True}]
            elif (spec or {}).get("restroom_style") == "oak_tile":      # kit key (floors G / H): an enclosed tiled WC cubicle with an ajar oak door + an oak vanity with a round brass mirror
                plan["furniture"] = [{"id": "wc", "category": "wc_cubicle", "relation": "corner", "avoid_windows": True},
                                     {"id": "basin", "category": "oak_vanity", "relation": "against_wall", "away_from": "wc", "avoid_windows": True}]
            out["rooms"][room["id"]] = {"plan": plan, "room": room}
            continue
        if room["type"] in ("bathroom", "kitchen") and room["type"] not in types:
            # home wet rooms get no LLM plan but must reach the realizer so REQUIRED_ITEMS places their fixtures / kitchen run (P2 r3: no [plan] line, no fixtures)
            kp_ = (((spec or {}).get("room_program") or {}).get(room["id"]) or {}) if room["type"] in ("kitchen", "bathroom") else {}      # a kit's room_program gives a kitchen its own fixed fit-out (floors G/H: a commercial kitchen)
            out["rooms"][room["id"]] = {"plan": {"occupant": "staff" if kp_ and room["type"] == "kitchen" and not home_ else "residents", "tidiness": 0.8, "lived_in": list(kp_.get("lived_in", [])), "furniture": list(kp_.get("fixed_furniture", [])), "fixed": True}, "room": room}
            continue
        if room["type"] not in types:
            continue
        payload = {k: v for k, v in room.items() if not k.startswith("_")}
        payload["existing"] = [{k: v for k, v in e.items() if not k.startswith("_")} for e in room["existing"]]
        plan = client.plan_room(payload, a.seed, dry_run=a.dry_run, images=room_images)
        if a.dry_run:
            print(json.dumps(plan["request"], indent=1)[:6000])
            return 0
        if prog and prog.get("forbid"):                              # kit room_program[id].forbid = categories the LLM must not add (B offices: no central table, no tall bookcase, no extra seating)
            bad_ = set(prog["forbid"]); plan = {**plan, "furniture": [f for f in plan.get("furniture", []) if f.get("category") not in bad_], "forbid": sorted(bad_),
                                                  "lived_in": [x for x in plan.get("lived_in", []) if x.get("category") not in bad_]}       # the forbid list covers the counter-top / floor dressing too (S32: register, cup stack, plates, cafe stock)
        if prog and prog.get("lived_in"):                            # kit room_program[id].lived_in added to the LLM plan; "on": "@counter" = the plan's first item of that category
            ids_ = {}
            for f_ in plan.get("furniture", []):
                ids_.setdefault(f_.get("category"), f_.get("id"))
            extra_ = []
            for x_ in prog["lived_in"]:
                on_ = ids_.get(x_["on"][1:]) if str(x_.get("on", "")).startswith("@") else x_.get("on")
                if on_:
                    extra_.append({**x_, "on": on_})
            plan = {**plan, "lived_in": plan.get("lived_in", []) + extra_}
        out["rooms"][room["id"]] = {"plan": plan, "room": room}        # the realizer needs the room's origin and object names
        print(json.dumps({"room": room["id"], "furniture": len(plan.get("furniture", [])), "lived_in": len(plan.get("lived_in", [])),
                          "occupant": plan.get("occupant")}, ensure_ascii=False), flush=True)
    if os.environ.get("ROOM_HOME_LIVED") == "1":                 # P2b r33 'sparse rooms': a fixed home room (bathroom / closet / kitchen / utility / hallway) with no lived_in gets 5-8 everyday items on the hosts its own fixed plan already has
        EXTRA = {"bathroom": [("towel", "floor", 1), ("laundry_basket", "floor", 1), ("small_plant", "vanity", 1), ("mug", "vanity", 1), ("storage_box", "floor", 1), ("bag", "floor", 1)],
                 "closet": [("pants", "floor", 1), ("bag", "floor", 2), ("storage_box", "floor", 2), ("laundry_basket", "floor", 1), ("towel", "floor", 1)],
                 "kitchen": [("fruit_bowl", "isl", 1), ("mug", "isl", 2), ("plate", "isl", 2), ("small_plant", "isl", 1), ("groceries", "run", 3), ("mug", "run", 1)],
                 "utility": [("laundry_basket", "floor", 1), ("cardboard_box", "floor", 2), ("storage_box", "floor", 2), ("bag", "floor", 1), ("towel", "floor", 1)],
                 "hallway": [("bag", "floor", 1), ("small_plant", "floor", 1), ("storage_box", "floor", 1)]}
        for rid_, ent_ in out["rooms"].items():
            pl_ = ent_["plan"]; rt_ = ent_["room"].get("type")
            if rt_ in EXTRA and pl_.get("fixed") and not pl_.get("lived_in"):
                ids_ = {f_.get("id") for f_ in pl_.get("furniture", [])}
                pl_["lived_in"] = [{"category": c_, "on": h_, "count": n_, "forced": True} for c_, h_, n_ in EXTRA[rt_] if h_ == "floor" or h_ in ids_]
    a.out.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
