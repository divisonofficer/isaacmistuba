"""Library-backed stand-ins for Infinigen's small-object factories (kit key object_library_v2 = true; data/object_library_v2 built by obj_gen.py). realize._cls returns lib_objects.factory(name) for the names in MAP
instead of the live factory: the activity pass calls cls(seed).spawn_asset(i) exactly as before and gets a finished object (same real size, origin at the base centre, +Z up) in ~ms instead of seconds.
  - repeats share mesh data (one mesh per (model, label) variant): linked duplicates;
  - packaging (FoodBox / FoodBag / Can / Bottle) gets a pack_atlas design (abstract art, no real brands) swapped into its label material by label_swap.swap; the Infinigen print stays on ~15 %;
  - None / the live factory when the library or the model is missing (factory() returns None -> realize falls back).
"""
import json
import random
from pathlib import Path
import bpy

ROOT = Path("/jarvis/project/robomituba/data/object_library_v2")
#: factory name -> (category, species prefixes, label swap)
MAP = {"FoodBoxFactory": ("package", "foodbox", True), "FoodBagFactory": ("package", "foodbag", True), "CanFactory": ("package", "can", True), "BottleFactory": ("package", "bottle", True),
       "JarFactory": ("package", "jar", False), "CupFactory": ("drinkware", "cup", False), "WineglassFactory": ("drinkware", "wineglass", False), "BowlFactory": ("dishes", "bowl", False),
       "PlateFactory": ("dishes", "plate", False), "PanFactory": ("cookware", "pan", False), "PotFactory": ("cookware", "pot", False), "VaseFactory": ("decor", "vase", False),
       "LibTowelFactory": ("clothes", "towel", False), "LibAppleFactory": ("fruit", "fruitapple", False), "LibFruitFactory": ("fruit", "fruitcompositional", False),
       "LibStrawberryFactory": ("fruit", "fruitstrawberry", False), "LibForkFactory": ("cutlery", "fork", False), "LibKnifeFactory": ("cutlery", "knife", False), "LibSpoonFactory": ("cutlery", "spoon", False)}          # fruit: only real_assets callers (kit shells) use these names          # library towels only where a scene asks for them (S37 daily needs); TowelFactory itself stays live elsewhere
_cache = {}


def _index():
    if "idx" not in _cache:
        try:
            _cache["idx"] = [m for m in json.load(open(ROOT / "index.json")) if not m.get("skip") and (ROOT / m["file"]).exists()]
        except Exception:                                        # noqa: BLE001
            _cache["idx"] = []
    return _cache["idx"]


CAP = 5000                                                    # polygons per small-object mesh: the library keeps 60k-face models; a 15 cm bottle needs ~10k, 8 stool sets x 60k faces would be 1.3 M per counter


def _decimated(me, cap):
    """A copy of mesh `me` collapsed to about `cap` polygons (a temporary object + DECIMATE, evaluated), or me itself when already small."""
    n = len(me.polygons)
    if n <= cap:
        return me
    tmp = bpy.data.objects.new("ir_tmp_dec", me); bpy.context.scene.collection.objects.link(tmp)
    md = tmp.modifiers.new("d", "DECIMATE"); md.ratio = max(0.02, cap / n)
    dg = bpy.context.evaluated_depsgraph_get(); out = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp, do_unlink=True)
    for ms in me.materials:
        out.materials.append(ms)
    return out


def _mesh(m, k):
    """The (model, label cell) mesh, built once."""
    key = (m["file"], k)
    me = _cache.get(key)
    if me is not None:
        return me
    base = _cache.get(("src", m["file"]))
    if base is None:
        with bpy.data.libraries.load(str(ROOT / m["file"]), link=False) as (a, b):
            b.objects = [n for n in a.objects if n == "ir_obj"]
        base = _cache[("src", m["file"])] = _decimated(b.objects[0].data, CAP)
    me = base.copy() if k is not None else base
    if k is not None:
        from room_planner import label_swap
        tmp = bpy.data.objects.new("ir_tmp", me); bpy.context.scene.collection.objects.link(tmp)
        label_swap.swap(tmp, k)
        bpy.data.objects.remove(tmp, do_unlink=True)
    _cache[key] = me
    return me


def factory(name):
    spec = MAP.get(name)
    if spec is None or not _index():
        return None
    cat, sp, swap = spec
    pool = [m for m in _index() if m["category"] == cat and m["species"] == sp]
    if not pool:
        return None

    class Lib:
        def __init__(self, seed):
            self.seed = seed

        def spawn_asset(self, i=0, **kw):
            r = random.Random(self.seed * 7919 + i)
            m = r.choice(pool)
            k = r.randrange(100) if swap and r.random() < 0.85 else None
            o = bpy.data.objects.new(f"{name}({self.seed}).spawn_asset({i})", _mesh(m, k)); bpy.context.scene.collection.objects.link(o)
            return o
    Lib.__name__ = name
    return Lib
