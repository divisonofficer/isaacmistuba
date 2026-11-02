"""Rebuild data/plant_library_v2/index.json from the *.json sidecars (keeps "skip" flags already set; adds the default drops). python3 plant_index.py"""
import json, glob, os
D = "/jarvis/project/robomituba/data/plant_library_v2"
old = {m["file"]: m for m in json.load(open(f"{D}/index.json"))} if os.path.exists(f"{D}/index.json") else {}
DROP = {"leafbananatree", "succulent", "palmtree"}                    # single leaf / fantasy colours / runaway memory
out = []
for f in sorted(glob.glob(f"{D}/*.json")):
    if f.endswith("index.json"):
        continue
    m = json.load(open(f)); m["file"] = os.path.basename(f)[:-5] + ".blend"
    if not os.path.exists(f"{D}/{m['file']}") or m["height"] != m["height"]:
        continue
    skip = old.get(m["file"], {}).get("skip") or m["species"] in DROP or (m["species"] == "agavemonocot" and m["seed"] in (1, 3, 5))
    if skip:
        m["skip"] = True
    out.append(m)
json.dump(out, open(f"{D}/index.json", "w"), indent=1)
print(len(out), "models,", sum(1 for m in out if m.get("skip")), "skipped")
