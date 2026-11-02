"""Reference objects missing from a round -> additions for the next plan (user 2026-10-22: find what the reference shows and the render lacks,
e.g. PH study: a second desk, a bookshelf with books, wall art, three plants, a window; then plan those in).

  refs_missing.py TAG ROUND                      print the shortfalls per room (from out/vlm_review/TAG_ROUND/<room>.json "missing_objects")
  refs_missing.py TAG ROUND --apply KIT.json     merge the furniture/decor shortfalls into KIT room_program[<room id>]["must_have"]
                                                 (count raised to the reference count; existing entries kept). Architecture items are only printed.
Rooms whose program has a "layout" (placed from layout.json) are printed as layout additions instead: their must_have is not used by the placer.
"""
import argparse, json, sys
from pathlib import Path

REPO = Path("/jarvis/project/robomituba")


def shortfalls(tag, rnd):
    out = {}
    for f in sorted((REPO / "out/vlm_review" / f"{tag}_{rnd}").glob("*.json")):
        miss = json.loads(f.read_text()).get("missing_objects") or []
        if miss:
            out[f.stem] = miss
    return out


def room_id(name, program):
    """review room name -> program key: 'office_0-0' -> 'office_0/0'; a single-room scene's 'cafe' -> its only program room"""
    rid = name[::-1].replace("-", "/", 1)[::-1] if "_" in name else name
    if rid not in program and len(program) == 1:
        rid = next(iter(program))
    return rid


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("tag"); ap.add_argument("round"); ap.add_argument("--apply", help="kit.json to update")
    a = ap.parse_args()
    sf = shortfalls(a.tag, a.round)
    if not sf:
        sys.exit(f"no missing_objects in out/vlm_review/{a.tag}_{a.round} (no inventory answer yet?)")
    kit = json.loads(Path(a.apply).read_text()) if a.apply else None
    prog = (kit or {}).get("room_program", {})
    changed = 0
    for room, miss in sf.items():
        rid = room_id(room, prog)
        layout_room = bool(prog.get(rid, {}).get("layout"))
        print(f"== {room} ({rid}){' [layout room: add these to layout.json]' if layout_room else ''}")
        for m in miss:
            tag = "ARCH " if m.get("kind") == "architecture" else ("NOCAT" if not m.get("category") else "     ")
            print(f"  {tag} {m.get('object')!s:28} cat={m.get('category')!s:18} ref {m.get('ref_count')} render {m.get('render_count')}  @ {m.get('where', '')}")
            if kit is None or layout_room or m.get("kind") == "architecture" or not m.get("category"):
                continue
            mh = prog.setdefault(rid, {}).setdefault("must_have", [])
            cur = next((x for x in mh if x.get("category") == m["category"]), None)
            if cur is None:
                mh.append({"category": m["category"], "count": int(m["ref_count"]), "where": f"(reference) {m.get('where', '')}".strip()}); changed += 1
            elif int(cur.get("count", 1)) < int(m["ref_count"]):
                cur["count"] = int(m["ref_count"]); changed += 1
    if kit is not None and changed:
        kit["room_program"] = prog
        Path(a.apply).write_text(json.dumps(kit, ensure_ascii=False, indent=1))
        print(f"applied {changed} must_have changes to {a.apply}")


if __name__ == "__main__":
    main()
