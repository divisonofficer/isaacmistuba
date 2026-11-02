"""Asset generation driven by the Anthropic API: a text brief (+ optional clean reference photos) -> a prop spec (prop_dsl JSON) saved for proc_generated.

    python3 -m room_planner.asset_agent prop "a white bin with four round holes, 0.55 m square, 1 m high" [--image a.jpg ...] [--model M] [--dry-run]
    python3 -m room_planner.asset_agent revise WhiteBin "the holes are too small; add a lid" [--image render.png]
    python3 -m room_planner.asset_agent list

Same conventions as client.py: key from ANTHROPIC_API_KEY or the mode-600 key file (never printed), gzip only, forced tool call where the model allows, one nudge, results cached
by hash (rerun = free), usage appended to usage.jsonl. Photos with people must NOT be passed (use the *_clean sets); the agent refuses paths containing no '_clean' unless --allow-raw.
The spec is checked by prop_dsl.validate; on problems the model gets them back once to fix. Pipeline steps that are not API calls (people removal in the Codex session, texture
generation scripts gen_*.py, layout modules) stay as they are; this module covers the prop-geometry step of every scene mode.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
from pathlib import Path

from room_planner import client, proc_generated
from room_planner.prop_dsl import MAX_EXTENT, MAX_PRIMS, validate

TOOL = {"name": "submit_prop_spec", "description": "Submit the prop as a list of coloured primitives.",
        "input_schema": {"type": "object", "required": ["name", "parts"], "properties": {
            "name": {"type": "string", "description": "CamelCase, e.g. WhiteBin; the factory will be <name>Factory"},
            "notes": {"type": "string"},
            "parts": {"type": "array", "items": {"type": "object", "required": ["material", "prims"], "properties": {
                "material": {"type": "object", "required": ["rgb", "rough"], "properties": {
                    "name": {"type": "string"}, "rgb": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "rough": {"type": "number"}, "metallic": {"type": "number"}, "emit": {"type": "number", "description": "emission strength; 0/absent = none"},
                    "kind": {"type": "string", "enum": ["stone", "wood", "metal", "fabric", "paint", "marble_black", "marble_white", "laminate", "plastic"]}}},
                "prims": {"type": "array", "items": {"type": "array", "description": "['box',cx,cy,cz,sx,sy,sz,yaw?] | ['cyl',[x0,y0,z0],[x1,y1,z1],r,n] | ['sph',[x,y,z],r,sub]"}}}}}}}}

SYSTEM = f"""You model props for a procedural interior renderer. Output ONE call to submit_prop_spec.
Conventions: metres; origin at the bottom centre of the object on the floor; the FRONT faces +X, the left side is +Y; z up. Primitives: box (centre, full sizes, optional yaw
about z), cyl (two end points, radius, segments 6-24), sph (centre, radius, icosphere subdivisions 1-3). At most {MAX_PRIMS} primitives, every coordinate within {MAX_EXTENT} m.
Group primitives by material (1-5 parts). Real-world proportions; recognisable silhouette first, detail second. Invent brands/text: never reproduce real logos or lettering.
Use emit for lit surfaces (signs, display cases). kind selects a scanned texture family where one fits (stone, wood, metal, fabric, paint)."""


def _blocks(paths, allow_raw):
    out = []
    for p in map(Path, paths):
        if not allow_raw and "_clean" not in str(p) and "render" not in p.name and "scratchpad" not in str(p):
            raise SystemExit(f"{p}: not a *_clean / render image (people photos stay local); pass --allow-raw to override")
        out.append({"type": "image", "source": {"type": "base64", "media_type": "image/png" if p.suffix == ".png" else "image/jpeg", "data": base64.b64encode(p.read_bytes()).decode()}})
    return out


def _call(req, key):
    path = client.CACHE / f"prop_{key}.json"
    if path.is_file():
        return json.loads(path.read_text())["spec"]
    import anthropic
    cl = anthropic.Anthropic(api_key=client._api_key(), max_retries=4, default_headers={"Accept-Encoding": "gzip, deflate"})
    t0 = time.time(); msgs = [cl.messages.create(**req)]
    spec = next((b.input for b in msgs[0].content if b.type == "tool_use"), None)
    for _ in range(2):                                                         # one nudge if it answered in prose, one repair if validate() complains
        problems = ["call submit_prop_spec"] if spec is None else validate(spec)
        if not problems:
            break
        req = {**req, "messages": req["messages"] + [{"role": "assistant", "content": msgs[-1].content}] + ([
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": next(b.id for b in msgs[-1].content if b.type == "tool_use"), "is_error": True,
                                          "content": "; ".join(problems)}]}] if spec is not None else [{"role": "user", "content": "Please submit it by calling submit_prop_spec."}])}
        msgs.append(cl.messages.create(**req)); spec = next((b.input for b in msgs[-1].content if b.type == "tool_use"), None)
    if spec is None or validate(spec):
        raise SystemExit(f"model gave no valid spec: {validate(spec) if spec else 'no tool call'}")
    usage = {"key": f"prop_{key}", "model": msgs[-1].model, "secs": round(time.time() - t0, 1), "calls": len(msgs),
             "input_tokens": sum(m.usage.input_tokens for m in msgs), "output_tokens": sum(m.usage.output_tokens for m in msgs)}
    client.CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"spec": spec, "usage": usage}, indent=1))
    with open(client.CACHE / "usage.jsonl", "a") as f:
        f.write(json.dumps(usage) + "\n")
    return spec


def request(brief, images=(), model=None, base=None, allow_raw=False):
    model = model or client.MODEL
    text = brief if base is None else f"Current spec:\n{json.dumps(base)}\n\nChange it as follows (keep the name): {brief}"
    req = {"model": model, "max_tokens": 8000, "system": SYSTEM, "tools": [TOOL], "messages": [{"role": "user", "content": _blocks(images, allow_raw) + [{"type": "text", "text": text}]}]}
    if model not in client.NO_FORCED_TOOL:
        req["tool_choice"] = {"type": "tool", "name": "submit_prop_spec"}
    key = hashlib.sha256(json.dumps({"s": SYSTEM, "r": {k: v for k, v in req.items() if k != "messages"}, "t": text, "i": [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in images]}, sort_keys=True).encode()).hexdigest()[:24]
    return req, key


def generate(brief, images=(), model=None, base=None, dry_run=False, allow_raw=False):
    req, key = request(brief, images, model, base, allow_raw)
    if dry_run:
        return {"key": key, "model": req["model"], "images": len(images), "chars": len(json.dumps(req["messages"]))}
    spec = _call(req, key)
    proc_generated.DIR.mkdir(parents=True, exist_ok=True)
    (proc_generated.DIR / f"{spec['name']}.json").write_text(json.dumps(spec, indent=1))
    return spec


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["prop", "revise", "list"]); ap.add_argument("text", nargs="*")
    ap.add_argument("--image", action="append", default=[]); ap.add_argument("--model"); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--allow-raw", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        print("\n".join(proc_generated.names()) or "(none)"); return 0
    base = None
    if a.cmd == "revise":
        name, *a.text = a.text; base = json.loads((proc_generated.DIR / f"{name}.json").read_text())
    r = generate(" ".join(a.text), a.image, a.model, base, a.dry_run, a.allow_raw)
    print(json.dumps(r if a.dry_run else {"saved": r["name"], "parts": len(r["parts"]), "prims": sum(len(p["prims"]) for p in r["parts"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
