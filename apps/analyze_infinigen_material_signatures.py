"""Classify Infinigen objects by their material-channel signature.

Per object (mesh): does it have UV? which baked PBR maps exist (albedo/metallic/
roughness/normal) and are they spatially-varying (std over threshold)? plus the
manifest optical_class / ior / is_glass / metallic-roughness scalars.

Aggregate by Factory type -> signature -> PBR-polarization readiness bucket.
"""
import sys, os, json, glob
from collections import defaultdict, Counter
import numpy as np
from PIL import Image

IMPORTS = sys.argv[1:] or ["out/infinigen_imports/kr_20260627"]
SUFFIXES = ["albedo", "metallic", "roughness", "normal"]
SPATIAL_STD = 0.04   # normalized [0,1] std above which a map is "spatially varying"


def factory_type(oid: str) -> str:
    return oid.split("Factory_")[0] if "Factory_" in oid else oid.split("_")[0]


def has_uv(obj_path: str) -> bool:
    # stop at first vt line
    try:
        with open(obj_path, "r", errors="ignore") as f:
            for ln in f:
                if ln.startswith("vt "):
                    return True
                # vt lines come after v lines; bail once faces start (no vt seen)
                if ln.startswith("f ") or ln.startswith("usemtl"):
                    return False
    except Exception:
        pass
    return False


def map_stat(path: str):
    """Return (exists, mean, std) of a map in [0,1]. Uses a small resize for speed."""
    if not os.path.exists(path):
        return (False, None, None)
    try:
        im = Image.open(path).convert("L").resize((64, 64))
        a = np.asarray(im, dtype=np.float32) / 255.0
        return (True, float(a.mean()), float(a.std()))
    except Exception:
        return (False, None, None)


def obj_materials(mtl_path: str):
    names = []
    if os.path.exists(mtl_path):
        for ln in open(mtl_path, errors="ignore"):
            if ln.startswith("newmtl"):
                names.append(ln.split(None, 1)[1].strip())
    return names


rows = []
for D in IMPORTS:
    man_path = os.path.join(D, "scene_manifest.json")
    if not os.path.exists(man_path):
        continue
    mats = json.load(open(man_path)).get("materials", {})
    tex = os.path.join(D, "textures")
    for obj in sorted(glob.glob(os.path.join(D, "meshes", "*.obj"))):
        oid = os.path.basename(obj)[:-4]
        ftype = factory_type(oid)
        matnames = obj_materials(obj[:-4] + ".mtl")
        # manifest per-material optical props (union over the object's materials)
        oclasses, iors, glass, mets, roughs = set(), [], False, [], []
        for mn in matnames:
            rec = mats.get(mn)
            if not rec:
                cand = [k for k in mats if k.split(".")[0] == mn.split(".")[0]]
                rec = mats.get(cand[0]) if cand else None
            if not rec:
                continue
            oclasses.add(rec.get("optical_class"))
            if rec.get("ior") is not None:
                iors.append(float(rec["ior"]))
            glass = glass or bool(rec.get("is_glass"))
            if rec.get("metallic") is not None:
                mets.append(float(rec["metallic"]))
            if rec.get("roughness") is not None:
                roughs.append(float(rec["roughness"]))
        sig = {}
        for suf in SUFFIXES:
            ex, mean, std = map_stat(os.path.join(tex, f"{oid}_{suf}.png"))
            sig[suf] = {"has": ex, "std": std, "spatial": bool(ex and std is not None and std > SPATIAL_STD)}
        rows.append({
            "import": os.path.basename(D), "oid": oid, "type": ftype,
            "optical_classes": sorted(x for x in oclasses if x),
            "is_glass": glass,
            "ior": (round(float(np.mean(iors)), 3) if iors else None),
            "metallic_scalar": (round(float(np.mean(mets)), 3) if mets else None),
            "roughness_scalar": (round(float(np.mean(roughs)), 3) if roughs else None),
            "uv": has_uv(obj),
            "albedo": sig["albedo"], "metallic": sig["metallic"],
            "roughness": sig["roughness"], "normal": sig["normal"],
        })

# ---- readiness bucket ---------------------------------------------------- #
def readiness(r):
    ocl = set(r["optical_classes"])
    if r["is_glass"] or (ocl & {"glass", "mirror"}):
        return "DIELECTRIC_SCALAR"      # IOR-only; polarization from Fresnel(IOR)
    if any(o and o.startswith("metal") for o in ocl):
        return "METAL"                   # conductor Fresnel(eta,k)
    # diffuse family
    if r["albedo"]["has"] and r["uv"]:
        return "DIFFUSE_TEXTURED"        # albedo map + uv; plastic specular lobe
    if r["albedo"]["has"]:
        return "DIFFUSE_MAP_NOUV"
    return "DIFFUSE_SCALAR"


for r in rows:
    r["readiness"] = readiness(r)

# ---- aggregate by type --------------------------------------------------- #
by_type = defaultdict(list)
for r in rows:
    by_type[r["type"]].append(r)

print(f"scanned {len(rows)} objects across {len(IMPORTS)} import(s)")
print(f"\nreadiness distribution: {dict(Counter(r['readiness'] for r in rows))}")
print(f"\n{'type':22} {'n':>3} {'uv%':>4} {'alb%':>4} {'rgh%':>4} {'met%':>4} {'metSV%':>6} {'nrm%':>4}  readiness(mode)  optcls")
def pct(rs, key, sub="has"):
    return int(100 * sum(1 for r in rs if r[key][sub]) / len(rs))
def pct_uv(rs):
    return int(100 * sum(1 for r in rs if r["uv"]) / len(rs))
for t, rs in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
    if len(rs) < 1:
        continue
    ready = Counter(r["readiness"] for r in rs).most_common(1)[0][0]
    ocl = Counter(o for r in rs for o in r["optical_classes"]).most_common(2)
    metsv = int(100 * sum(1 for r in rs if r["metallic"]["spatial"]) / len(rs))
    print(f"{t:22} {len(rs):>3} {pct_uv(rs):>4} {pct(rs,'albedo'):>4} {pct(rs,'roughness'):>4} "
          f"{pct(rs,'metallic'):>4} {metsv:>6} {pct(rs,'normal'):>4}  {ready:16} {ocl}")

# save raw for the report builder
out = "infinigen_object_signatures.json"
json.dump(rows, open(out, "w"), indent=1)
print(f"\nsaved per-object rows -> {out}")
