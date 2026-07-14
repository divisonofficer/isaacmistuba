"""Render-time material analysis for Infinigen imports.

For each placed shape in a scene's ``render_scene.xml`` this recovers what the
renderer *actually* uses: the injected BSDF's optical class (metal / dielectric /
plastic-diffuse), whether that BSDF binds image textures, and whether the mesh the
shape loads carries UVs. From those three it derives:

  * optical class  -> polarization readiness (metal & dielectric = Fresnel-defined)
  * texture consumption -> TEXTURE_OK (uv+texture) / TEXTURE_BROKEN (texture bound
    but no UV, so Mitsuba samples it at per-triangle barycentric coords -> garbled)
    / FLAT_RGB (no texture, single base color)

This supersedes the per-baked-file scan (apps/analyze_infinigen_material_signatures.py):
the render pipeline SHARES a BSDF per material identity, so many instances without
their own baked map still render with a shared textured BSDF — and a bound texture
is only truly consumed when the mesh (extracted from the source OBJ) actually has UVs.

Usage: python3 apps/analyze_infinigen_rendertime_materials.py <scene_dir> [<scene_dir> ...]
       (scene_dir = out/opticalnav/opticalnav-v0.2/scenes/<scene_id>)
"""
import sys, os, re, json
from collections import Counter

METAL_BSDF = {"roughconductor", "conductor"}
GLASS_BSDF = {"dielectric", "roughdielectric", "thindielectric"}
PLASTIC_BSDF = {"pplastic", "roughplastic", "plastic", "diffuse", "principled"}
WRAPPERS = {"twosided", "normalmap", "bumpmap", "mask", "blendbsdf"}


def core_type(block: str) -> str:
    inner = re.findall(r'<bsdf type="([a-z]+)"', block)
    core = [t for t in inner if t not in WRAPPERS]
    return core[-1] if core else (inner[-1] if inner else "?")


def optical_class(btype: str) -> str:
    if btype in METAL_BSDF:
        return "metal"
    if btype in GLASS_BSDF:
        return "dielectric"
    if btype in PLASTIC_BSDF:
        return "plastic/diffuse"
    return "other"


def factory_type(shape_id: str) -> str:
    return shape_id.split("Factory_")[0] if "Factory_" in shape_id else re.split(r"[_.]", shape_id)[0]


def _bsdf_block(s: str, start: int) -> str:
    k, depth = start, 0
    while k < len(s):
        if s.startswith("<bsdf", k):
            depth += 1
        elif s.startswith("</bsdf>", k):
            depth -= 1
            if depth == 0:
                return s[start:k + 7]
        k += 1
    return s[start:k]


def _mesh_has_uv(path: str, cache: dict) -> bool:
    if path in cache:
        return cache[path]
    ok = False
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
        ok = (b"\nvt " in data) or data.startswith(b"vt ")
    cache[path] = ok
    return ok


def parse_scene(scene_dir: str):
    s = open(os.path.join(scene_dir, "render_scene.xml")).read()
    bsdfs = {}
    for m in re.finditer(r'<bsdf [^>]*id="([^"]+)"', s):
        block = _bsdf_block(s, m.start())
        bsdfs[m.group(1)] = (core_type(block), "<texture" in block)
    uv_cache: dict = {}
    rows = []
    for m in re.finditer(r'<shape type="obj" id="([^"]+)">(.*?)</shape>', s, re.S):
        sid, body = m.group(1), m.group(2)
        fn = re.search(r'filename" value="([^"]+)"', body)
        ref = re.search(r'<ref id="([^"]+)"', body)
        btype, textured = bsdfs.get(ref.group(1), ("?", False)) if ref else ("?", False)
        uv = _mesh_has_uv(fn.group(1), uv_cache) if fn else False
        consume = "FLAT_RGB" if not textured else ("TEXTURE_OK" if uv else "TEXTURE_BROKEN")
        rows.append({"scene": os.path.basename(scene_dir), "shape_id": sid,
                     "type": factory_type(sid), "bsdf": btype,
                     "optical": optical_class(btype), "textured": textured,
                     "uv": uv, "consume": consume})
    return rows


def main():
    rows = []
    for d in (sys.argv[1:] or ["out/opticalnav/opticalnav-v0.2/scenes/infinigen_kr_20260627"]):
        rows += parse_scene(d)
    print(f"render-time shapes analysed: {len(rows)}\n")
    print("optical class (injected BSDF):", dict(Counter(r["optical"] for r in rows)))
    print("texture consumption:          ", dict(Counter(r["consume"] for r in rows)))
    opts, cons = ["metal", "dielectric", "plastic/diffuse", "other"], ["TEXTURE_OK", "TEXTURE_BROKEN", "FLAT_RGB"]
    print("\noptical x consumption (counts):")
    print(f"{'':16} " + " ".join(f"{c:>15}" for c in cons))
    for o in opts:
        print(f"{o:16} " + " ".join(
            f"{sum(1 for r in rows if r['optical']==o and r['consume']==c):>15}" for c in cons))
    out = "infinigen_rendertime_signatures.json"
    json.dump(rows, open(out, "w"), indent=1)
    print(f"\nsaved -> {out}")


if __name__ == "__main__":
    main()
