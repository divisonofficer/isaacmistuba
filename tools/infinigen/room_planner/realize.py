"""Turn room plans (plan_scene.py: Claude) into placed objects, inside the activity pass (Blender).

Every furniture item resolves its relation to a list of candidate (x, y, yaw) spots, tried in order through furnish_rooms._place:
standing on the room's own floor, clear of every footprint (and door zone) by 5 cm. An item whose target is placed later in the plan is
retried after the rest; one with no valid spot is dropped and counted (stats["plan_dropped"]). Lived-in items go on their host's
support surfaces through the activity pass's put(), or on free floor.

Room frame -> world: + room["_origin"]. Existing objects are found by name (extract_rooms "_name").
"""
from __future__ import annotations

import importlib
import json
import os
import itertools
import math
import time
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

import furnish_rooms as fr
import room_dressing as rd
from room_planner import catalog
from room_planner.extract_rooms import inside

INF = {"OfficeChairFactory": "seating.chairs.office_chair", "ChairFactory": "seating.chairs.chair", "SimpleDeskFactory": "shelves.simple_desk",
       "SimpleBookcaseFactory": "shelves.simple_bookcase", "TVStandFactory": "shelves.cell_shelf",
       "LargePlantContainerFactory": "tableware.plant_container", "BlanketFactory": "clothes.blanket", "PillowFactory": "seating.pillow",
       "BookStackFactory": "table_decorations.book", "CupFactory": "tableware.cup", "FruitContainerFactory": "tableware.fruit_container",
       "ShirtFactory": "clothes.shirt", "BasketBaseFactory": "organizer.basket", "PantsFactory": "clothes.pants", "TowelFactory": "clothes.towel",
       "BookFactory": "table_decorations.book", "LargeShelfFactory": "shelves.large_shelf", "BottleFactory": "tableware.bottle",
       "CanFactory": "tableware.can", "FoodBoxFactory": "tableware.food_box", "FoodBagFactory": "tableware.food_bag", "BalloonFactory": "wall_decorations.balloon", "JarFactory": "tableware.jar",
       "MonitorFactory": "appliances.tv", "ToiletFactory": "bathroom.toilet", "BathtubFactory": "bathroom.bathtub", "BedFactory": "seating.bed", "StandingSinkFactory": "bathroom.bathroom_sink", "TableDiningFactory": "tables.dining_table", "PlateFactory": "tableware.plate",
       "WineglassFactory": "tableware.wineglass", "BeverageFridgeFactory": "appliances.beverage_fridge", "CupFactory": "tableware.cup",
       "BowlFactory": "tableware.bowl", "MicrowaveFactory": "appliances.microwave"}
#: spacing between items of a `row`: _place keeps 5 cm between footprints, so a 3 cm gap made every second rack / gondola / stool
#: in a row collide with the first (warehouse: 7 racks dropped; grocery aisles; window-bar stools -- 2026-10-16)
ROW_GAP = 0.07
#: ROOM_RELAX_ZONES=1 (home recipes): small-room furniture that found no spot retries with the door zones cut to the casing + 0.4 / 0.05 m (P2 r6: study desk + chair in a 5 m2 room with two doors)
RELAX_ZONES = os.environ.get("ROOM_RELAX_ZONES") == "1"
RELAX_CATS = ("wall_gondola", "staircase", "elevator_door", "notice_panel", "gas_cart", "gas_rack", "lab_cabinet", "lab_chamber", "workbench", "single_bed", "balcony_table", "balcony_chair", "rug", "home_kitchen_run", "shower_glass", "wash_basin", "storage_rack", "wc", "vanity", "office_desk", "desk_chair", "dining_chair", "coffee_table", "nightstand", "floor_plant", "armchair", "sofa", "bookshelf", "waiting_bench", "clinic_desk", "reception_desk", "bar_stool", "oak_vanity_long", "open_wardrobe", "pallet", "wide_shelf", "box_pile", "ladder", "pallet_rack", "laundry_run", "oak_wardrobe", "big_fridge", "kitchen_island", "towel_rail", "media_wall", "bedroom_media", "bed_bench")
SHRINKABLE = ("staircase", "counter", "backbar_shelf", "window_bar", "medical_cabinet", "reception_desk", "banquette", "privacy_curtain", "storage_rack",
              "clinic_desk", "stock_shelf", "supply_shelf", "exercise_set", "wall_gondola", "waiting_bench", "ceramic_shelf", "home_kitchen_run", "laundry_run", "oak_wardrobe", "media_wall", "bedroom_media", "prep_table", "supply_shelf", "oak_vanity_long", "open_wardrobe", "wide_shelf", "pallet_rack")   # shelves too: two of three found no wall, a one-rack stockroom (G r24)   # floor D3 r5: an exam room with no desk (wall and corner both failed), 3 of 3
HARD_AVOID_WINDOWS = ("lab_chamber", "lab_cabinet", "instrument_rack")                # avoid_windows with no fallback onto a window span
SEATS = ("desk_chair", "conference_chair", "cafe_chair", "break_chair", "bar_stool", "dining_chair", "balcony_chair")
TABLES = ("break_table", "meeting_table", "dining_table", "cafe_table", "workbench", "balcony_table")
SHELVES = ("SimpleBookcaseFactory", "LargeShelfFactory", "CellShelfFactory", "TVStandFactory", "AboRackFactory", "AboBookcaseFactory",
           "BackBarShelfFactory", "GondolaFactory", "WallGondolaFactory", "StorageRackFactory")
#: hosts with soft, curved tops: the surface grid finds no flat level there, so things are dropped on them with physics instead
SOFT = ("SofaFactory", "BedFactory", "ArmChairFactory", "ChairFactory", "OfficeChairFactory", "BarChairFactory", "AboSofaFactory",
        "AboArmchairFactory")


T0 = time.time()


def _log(msg):
    print(f"[realize {time.time() - T0:7.1f}s] {msg}", flush=True)


#: modules holding the proc: factories that are not in proc_assets (searched in order); every new scene mode appends its module here, nowhere else
PROP_MODULES = ["proc_lp", "proc_bookstore", "proc_boutique_flagship", "proc_rooftop", "proc_winepub", "proc_clinic_lobby", "proc_museum", "proc_generated", "proc_market", "proc_lab", "proc_grocery", "proc_home", "proc_building", "proc_office", "proc_lounge", "proc_atrium", "proc_pharmacy", "proc_boutique_shelf", "proc_cafeteria", "proc_parking", "proc_officefloor", "proc_lobby"]


def _cls(src):
    if src == "abo:PLANTER" and proc_assets_kit().STYLE.get("plant_style") == "ficus":
        src = "proc:SmallFicusFactory"                           # kit plant_style=ficus covers the small potted plants too (B r18: ABO planters = 'single-stem jagged broad-leaf')
    kind, name = src.split(":")
    if kind == "proc" and ((name == "TaskChairFactory" and os.environ.get("ROOM_TASK_CHAIR_LIB") == "1") or (name == "ConferenceChairFactory" and os.environ.get("ROOM_CONF_CHAIR_LIB") == "1")):
        from room_planner import chair_lib                       # P4: library office chairs (Office Hippo / AmazonBasics; HSSD Margot for meeting rooms), front found from the geometry
        return chair_lib.LibTaskChairFactory if name == "TaskChairFactory" else chair_lib.LibConfChairFactory
    if kind == "proc":
        from room_planner import proc_assets
        if not hasattr(proc_assets, name):                       # props of the scene modes live in their own modules: add a new module to PROP_MODULES only
            for modname in PROP_MODULES:
                mod = importlib.import_module("room_planner." + modname)
                if hasattr(mod, name):
                    return getattr(mod, name)
            raise AttributeError(f"no prop module defines {name}: {PROP_MODULES}")
        return getattr(proc_assets, name)
    if kind == "abo":
        import abo_assets as abo
        return getattr(abo, name)
    if proc_assets_kit().STYLE.get("object_library_v2"):         # kit object_library_v2: finished Infinigen small objects from data/object_library_v2 (lib_objects.py), pack_atlas labels swapped in; live factory when absent
        from room_planner import lib_objects
        lib = lib_objects.factory(name)
        if lib is not None:
            return lib
    cls = getattr(importlib.import_module("infinigen.assets.objects." + INF[name]), name)
    return _wheeled(cls) if name == "OfficeChairFactory" else cls


def _safe_cls(src):
    """_cls that returns None (and warns) for an unknown factory, so one bad name in a fill mix is skipped, not fatal."""
    try:
        return _cls(src)
    except Exception as ex:                                      # noqa: BLE001
        print(f"[realize] fill mix: {src} skipped: {ex!r}"[:160], flush=True)
        return None


def proc_assets_kit():
    from room_planner import proc_assets
    return proc_assets


_CHAIR_SEED = []


def _wheeled(base):
    """OfficeChairFactory draws 'single_stand' (a shell on one post -- reads as a bar stool at a desk, critic r6) or 'wheeled'; only
    the wheeled variant has 'Leg Wheel Width' in its params, so seeds are re-drawn until one is."""
    class WheeledOfficeChairFactory(base):
        def __init__(self, factory_seed, *a, **k):
            # one chair model per scene (one process per scene): the first wheeled seed is reused for every chair (office r8/r9:
            # 'dark task chairs and white shell chairs mixed in one pod / at one table', 3 of 3 both rounds)
            seeds = [_CHAIR_SEED[0]] if _CHAIR_SEED else range(int(factory_seed), int(factory_seed) + 40)
            for s in seeds:
                super().__init__(s, *a, **k)
                if "Leg Wheel Width" in self.params:
                    _CHAIR_SEED[:] = [s]
                    break
            try:                                                 # black metal base: the leg pool's colours gave purple/green
                from infinigen.assets.materials import metal       # five-star bases (r7)
                self.params["LegMaterial"] = metal.BrushedBlackMetal()()
            except Exception as e:                               # keep the drawn material rather than fail the room
                print(f"[realize] office chair leg material kept: {e}", flush=True)
    WheeledOfficeChairFactory.__name__ = "OfficeChairFactory"           # keeps rd._factory names / SOFT matching unchanged
    return WheeledOfficeChairFactory


def _frame(o, front):
    """(centre, unit front, width, depth) of o in world xy."""
    f = fr.footprint(o)
    fwd = o.matrix_world.to_3x3() @ Vector((*front, 0)); fwd.z = 0; fwd.normalize()
    lx, ly = (o.dimensions[1], o.dimensions[0]) if abs(front[0]) > 0.5 else (o.dimensions[0], o.dimensions[1])   # (width, depth)
    return Vector(((f[0] + f[1]) / 2, (f[2] + f[3]) / 2, 0)), fwd, lx, ly


def _yaw(v):
    return math.atan2(v.y, v.x)


def _left(v):
    return Vector((-v.y, v.x, 0))



def _frange(a, b, step):
    out = []
    while a <= b + 1e-9:
        out.append(a); a += step
    return out

# printed packaging for shelf goods (user 2026-10-17: 'every product in that shop is a textureless single-colour block'): 24 front /
# unrolled label designs of invented brands, generated for this (data/venue_refs/product_labels, synthetic=true); they replace the
# random text-art image of Infinigen's FoodBox / FoodBag / Bottle / Can / Jar label material, on its own UV wrap
#: flagship boutique (reference set boutique_large_flagship_01): wall rails + stone tables + lattice screens in _fill_boutique; opt-in
FLAGSHIP = os.environ.get("ROOM_FLAGSHIP") == "1"
FLAGSHIP_CATS = ("stone_table", "clothing_rack", "lattice_screen", "stone_table")
MODE = os.environ.get("ROOM_MODE", "")                  # a deterministic single-room mode: room_planner/<mode>_layout.py (lounge / cafeteria / parking ...), _fill_mode places it
MODE_TYPES = tuple(t for t in os.environ.get("ROOM_MODE_TYPES", "").split(",") if t)   # floors: ROOM_MODE applies only to rooms of these types (S29 floor: break-room = the lounge, not the restrooms)
LAB = os.environ.get("ROOM_LAB") == "1"                # research-building corridor (floor N): _fill_lab_corridor stands chambers and gas racks along one corridor wall
BOOKSTORE = os.environ.get("ROOM_BOOKSTORE") == "1"      # underground bookstore: _fill_bookstore replaces the boutique fill
ROOFTOP = os.environ.get("ROOM_ROOFTOP") == "1"          # rooftop fine-dining restaurant (cafe venue): _fill_rooftop replaces fill_empty
ROOFTOP_CATS = {"banquette": "rt_banquette", "velvet_booth": "rt_booth", "marble_table_low": "rt_table_low", "marble_table_high": "rt_table_high",
                "marble_table_round": "rt_table_round", "cube_ottoman": "rt_ottoman", "mirror_column": "rt_mirror_column", "floor_ac": "rt_floor_ac",
                "patio_heater": "rt_heater", "counter": "counter", "timber_column": "rt_timber"}
CLINIC_LOBBY = os.environ.get("ROOM_CLINIC_LOBBY") == "1"   # warm clinic reception lobby (venue 'clinic-reception'): _fill_clinic_lobby goes first in run()
LOBBY_CATS = {"wood_wall": "cl_wood_wall", "oak_desk": "cl_desk", "beige_sofa": "cl_sofa", "oak_armchair": "cl_armchair", "round_table": "cl_table", "jute_rug": "cl_rug",
              "wall_art": "cl_art", "floor_plant": "floor_plant"}
MUSEUM = os.environ.get("ROOM_MUSEUM") == "1"           # science museum (venue 'boutique'): _fill_museum goes first in run()
MUSEUM_CATS = {"rail_ring": "mu_rail", "glow_ring": "mu_ring", "pendulum": "mu_pendulum", "element_wall": "mu_elements", "nebula_panel": "mu_nebula",
               "marble_bench": "mu_bench", "pic_blue": "mu_pic_blue", "pic_ring": "mu_pic_ring", "pic_earth": "mu_pic_earth"}
WINEPUB = os.environ.get("ROOM_WINEPUB") == "1"          # underground wine pub (cafe venue): _fill_winepub replaces the cafe fill
WINEPUB_CATS = {"bar_counter": "wp_bar", "bottle_shelf": "wp_shelf", "bottle_row": "wp_bottle_row", "round_table": "wp_table", "velvet_chair": "wp_chair",
                "mirror_wall": "wp_mirror_wall", "mirror_column": "wp_column"}
ROOFTOP_CHANDELIERS = ("PH_Chandelier_01", "PH_Chandelier_02", "PH_Chandelier_03", "PH_chinese_chandelier")
REAL_FURNITURE = {"desk_chair": "officechair", "conference_chair": "officechair", "meeting_table": "conftable"}   # category -> furnish_rooms ABO pool
LABELS = Path("/jarvis/project/robomituba/data/venue_refs/product_labels")
LABEL_POOL = {"FoodBoxFactory": ("box_snack", "box_cereal", "box_ramen", "box_tea"), "FoodBagFactory": ("bag_chips",),
              "BottleFactory": ("label_drink",), "CanFactory": ("label_can",), "JarFactory": ("label_milk",)}

GROCERY_LABELS = {"FoodBoxFactory": ("gro_box",), "FoodBagFactory": ("gro_bag",), "BottleFactory": ("gro_bottle",), "CanFactory": ("gro_can",), "JarFactory": ("gro_jar",)}   # muted gourmet packs (gen_grocery_labels.py)


LABELS_V2 = Path("/jarvis/project/robomituba/data/venue_refs/product_labels_v2")
_V2 = {"FoodBoxFactory": ("box_snack", "box_cereal", "box_ramen", "box_tea", "food_pack", "clean", "baby_pet"), "FoodBagFactory": ("bag_chips", "bag_snack", "coffee_bag"),
       "BottleFactory": ("label_drink", "food_bottle", "drink_bottle"), "CanFactory": ("label_can", "food_canned", "drink_can"), "JarFactory": ("label_milk", "food_jar", "dairy")}
VENUE_LABELS = {                                              # per venue: factory kind -> file prefixes drawn from product_labels + product_labels_v2 (+ gro_* / med_box_*)
    "grocery": {"FoodBoxFactory": _V2["FoodBoxFactory"] + ("gro_box", "bakery_bag"), "FoodBagFactory": _V2["FoodBagFactory"] + ("gro_bag",),
                "BottleFactory": _V2["BottleFactory"] + ("gro_bottle", "drink_wine"), "CanFactory": _V2["CanFactory"] + ("gro_can",), "JarFactory": _V2["JarFactory"] + ("gro_jar",)},
    "convenience": {**_V2, "FoodBoxFactory": _V2["FoodBoxFactory"] + ("care_box",)},
    "pharmacy": {"FoodBoxFactory": ("med_box", "otc", "care_box"), "BottleFactory": ("otc", "care_box"), "CanFactory": ("otc",), "JarFactory": ("otc", "care_box"), "FoodBagFactory": ("otc",)},
    "cafe": {"FoodBoxFactory": ("box_tea", "bakery_bag", "box_snack"), "FoodBagFactory": ("coffee_bag", "bag_snack"), "BottleFactory": ("drink_bottle", "food_bottle", "drink_wine"),
             "CanFactory": ("drink_can",), "JarFactory": ("food_jar", "label_milk")},
    "bakery": {"FoodBoxFactory": ("bakery_bag", "box_snack"), "FoodBagFactory": ("bakery_bag", "bag_snack"), "JarFactory": ("food_jar",)},
    "liquor": {"FoodBoxFactory": ("drink_wine",), "FoodBagFactory": ("coffee_bag",), "BottleFactory": ("drink_wine",), "CanFactory": ("drink_can",), "JarFactory": ("food_jar",)},   # kit label_venue (S38 r6: pet treats / chips on wine gondolas)
}


def _label_files(kind, venue):
    venue = proc_assets_kit().STYLE.get("label_venue") or venue
    prefixes = VENUE_LABELS.get(venue, {}).get(kind) or _V2.get(kind, ())
    return sorted(f for d in (LABELS, LABELS_V2) if d.is_dir() for p_ in prefixes for f in d.glob(p_ + "_*.png"))


def _shelf_labels(o, rng):
    kind = rd._factory(o.name)
    if kind not in LABEL_POOL or not LABELS.is_dir():
        return
    venue = proc_assets_kit().VENUE
    if kind == "FoodBoxFactory" and venue == "pharmacy":
        from room_planner import pharmacy_boxes as _pb          # ROOM_PHARMACY_BOXES=1 / kit pharmacy_boxes: Infinigen's paper box, albedo swapped for pharmacy label art, carton sizes
        if _pb.enabled() and _pb.restyle(o, rng):
            return
    files = _label_files(kind, venue)
    if not files:                                             # nothing matches: the first-batch pools as before
        pool = ("med_box",) if kind == "FoodBoxFactory" and venue == "pharmacy" else GROCERY_LABELS.get(kind, LABEL_POOL[kind]) if venue == "grocery" else LABEL_POOL[kind]
        files = sorted(LABELS.glob(rng.choice(pool) + "_*.png"))
    if not files:
        return
    if kind == "FoodBagFactory" and max(o.dimensions[0], o.dimensions[1]) < 0.12:
        return                                               # a stick pack / tube: the whole label wrapped round a 5 cm tube read as 'oversized fragmented lettering' (S13 r2): keep its own small text
    img = bpy.data.images.load(str(rng.choice(files)), check_existing=True)
    if kind == "FoodBagFactory" and o.type == "MESH" and o.data.uv_layers.active is not None and not o.data.get("side_uv_fixed"):
        uvl = o.data.uv_layers.active.data                   # the pouch's gusset (+-X) faces carried the whole label squeezed into a strip: point them at the label's plain top margin
        fr_ = [li for p_ in o.data.polygons if abs(p_.normal.y) > 0.7 for li in p_.loop_indices]
        if fr_:                                              # the front / back faces show only u 0.08-0.92 of the label: stretch to the whole label so the lettering is not clipped
            u0 = min(uvl[li].uv[0] for li in fr_); u1 = max(uvl[li].uv[0] for li in fr_)
            if u1 - u0 > 0.2:
                for li in fr_:
                    uvl[li].uv = ((uvl[li].uv[0] - u0) / (u1 - u0), uvl[li].uv[1])
        for p_ in o.data.polygons:
            if abs(p_.normal.x) > 0.7:
                for li in p_.loop_indices:
                    uvl[li].uv = (0.5, 0.965)
        o.data["side_uv_fixed"] = True
    for slot in o.material_slots:
        m = slot.material
        if m is not None and m.name.startswith("shader_text") and m.use_nodes:
            for nd in m.node_tree.nodes:
                if nd.type == "TEX_IMAGE":
                    nd.image = img


class RoomRealizer:
    def __init__(self, room_doc, room, rng, stats, spawn, act, obstacles, rugzones, t, revise=None):
        self.doc, self.room, self.rng, self.stats, self.spawn, self.act, self.t = room_doc, room, rng, stats, spawn, act, t
        self.revise = revise                                     # (plan, report) -> revised plan | None
        self.obstacles, self.rugzones = obstacles, rugzones
        self.mode = MODE if (not MODE_TYPES or str(room_doc.get("type", "")) in MODE_TYPES) else ""   # per room: a floor runs the mode only in its own room type
        ox, oy = room_doc["_origin"]
        self.poly = [(x + ox, y + oy) for x, y in room_doc["outline"]]
        self.centre = Vector((sum(x for x, _ in self.poly) / len(self.poly), sum(y for _, y in self.poly) / len(self.poly), 0))
        self.walls = {}
        for w in room_doc["walls"]:
            a, b = Vector((w["p0"][0] + ox, w["p0"][1] + oy, 0)), Vector((w["p1"][0] + ox, w["p1"][1] + oy, 0))
            t_ = (b - a).normalized(); n = _left(t_)
            mid = (a + b) / 2
            if not inside((mid + n * 0.2)[:2], self.poly):
                n = -n
            self.walls[w["id"]] = (a, t_, n, w["length"])
        if str(room_doc.get("id", "")).split("_")[0] in ("utility", "closet", "kitchen") or room_doc.get("type") == "office":
            # private offices too: the desk and its chair stood in the door swing (floors C r9, F3 r13: 'you walk into the desk', 3/3)
            # small back rooms only otherwise: in every work room the
            # extra boxes starved the gym, reception and treatment rooms (floor F3 r11: island, bike, kit, clinic desk all 'no spot')
            # the leaf's whole swing stays clear: the 0.9 m casing box left racks and tables inside a 1.2 m leaf's arc (floor H r15:
            # 'the door swings into the rack', 'table against the door', 3 of 3)
            for dr in room_doc.get("doors", []):
                if dr["wall"] not in self.walls:
                    continue
                a_, t_, n_, L_ = self.walls[dr["wall"]]
                w_ = dr.get("width", 1.0)
                c_ = a_ + t_ * dr["at_m"]
                pts = [c_ + t_ * sg * (w_ / 2 + 0.1) + n_ * dd for sg in (1, -1) for dd in (0.0, min(w_, 1.0) + 0.1)]
                self.obstacles.append((min(q.x for q in pts), max(q.x for q in pts), min(q.y for q in pts), max(q.y for q in pts), 0, 0))
            if room_doc.get("type") == "office" and os.environ.get("ROOM_OFFICE_TIGHT_DOORS", "1") != "0":
                self._tight_door_zones(0.15)                     # furnish_rooms' 0.9 m clearance round every casing PLUS the swing box above left no desk spot in a 2.7 m office with two doors (O3 r1: office_0/5 had no desk, chair or guest chairs)
        self.ids = {}                                            # plan id / existing id -> (object, front axis)
        for e in room_doc["existing"]:
            o = bpy.data.objects.get(e.get("_name", ""))
            if o is not None:
                self.ids[e["id"]] = (o, fr.INF_FRONT)

    # ---- spawning -----------------------------------------------------------------------------------------------------------------
    def _make(self, cat):
        spare = getattr(self, "spare", {}).get(cat)
        if spare:                                                # spawned for an item that found no spot: reuse, do not regrow
            return spare.pop()
        if WINEPUB and cat == "cafe_chair":                      # the pub's chairs are all the velvet shell chair: the plan's ABO café chairs faced away from the tables (S23 r6 LAY-02)
            cat = "wp_chair"
        src = catalog.FURNITURE[cat]["src"]
        from room_planner import proc_assets as _pa
        if cat == "office_desk":                                 # a small room gets the compact desk (1.0 x 0.5 m): the default 1.4-1.8 m desk did not fit a 1.9 x 1.4 m free area (O4 private offices / phone booth)
            _rx0, _rx1, _ry0, _ry1 = self.room.box
            _pa.OfficeDeskFactory.COMPACT = (_rx1 - _rx0) * (_ry1 - _ry0) < 8.5 or min(_rx1 - _rx0, _ry1 - _ry0) < 2.2
        real = REAL_FURNITURE.get(cat) if os.environ.get("ROOM_REAL_FURNITURE") == "1" and \
            self.doc.get("type") in ("office", "open-office", "meeting-room") else None
        if real is not None:                                     # opt-in A/B (user 2026-10-17: the procedural furniture reads as toy blocks):
            return fr.AboPick(real, self.rng).spawn(self.stats["furniture_added"]), fr.ABO_FRONT   # a scanned ABO model of that kind
        if _pa.STYLE.get("dining_style") == "stone_white" and cat in ("dining_table", "dining_chair"):
            src = "proc:StoneDiningTableFactory" if cat == "dining_table" else "proc:WhiteDiningChairFactory"      # kit: a pale stone table + white upholstered chairs (P2b r3: dark wood table, plum chairs vs the reference)
        if cat == "bar_stool" and _pa.STYLE.get("bar_stool_style"):
            src = "proc:ShapedStoolFactory"                      # kit bar_stool_style = roundback | spindle: a shaped stool, not the ABO slab-back one (S31 / S33 AST-01)
        if cat == "armchair" and (_pa.STYLE.get("armchair_rgb_by_room") or {}).get(str(self.doc.get("id", ""))):
            src = "proc:AccentArmchairFactory"                   # kit: the suite's accent-colour tub chair (hotel floors H2 / H3: grey / green / blue / pink rooms)
        if cat == "sofa" and (_pa.STYLE.get("sofa_rgb_by_room") or {}).get(str(self.doc.get("id", ""))):
            src = "proc:LoveseatFactory"
        if cat == "bed" and _pa.STYLE.get("bed_style") == "soft_white":
            src = "proc:SoftBedFactory"                          # kit: a soft white quilt + teal throw king bed (P2b r3: dark mixed angular bedding, brick-like headboard)
        if cat == "coffee_table" and _pa.STYLE.get("coffee_table_style") == "stone":
            src = "proc:StoneCoffeeTableFactory"
        if cat == "sofa" and _pa.STYLE.get("sofa_style") == "sectional":
            src = "proc:SectionalSofaFactory"                    # kit: the reference's large L-shaped corner sectional (P2b r3: 'small dark sofa')
        if cat == "floor_plant" and os.environ.get("ROOM_PLANT_LIBRARY", "1") != "0" and any(_pa.PLANT_LIB.glob("plant_*.blend")):
            src = "proc:OliveTreeFactory"                        # floor plants come from Infinigen's own offline-grown plant library (data/plant_library, pot + scale in OliveTreeFactory._from_library), not the live LargePlantContainer generator (crashes); user rule 2026-10-21: plants are Infinigen's
        if cat == "floor_plant" and _pa.STYLE.get("plant_style") == "ficus":
            src = "proc:FicusPlantFactory"                       # kit: a smooth-leaved ficus; Infinigen's LargePlantContainer read as 'jagged flat blades' in every B office
        if cat == "cafe_chair" and _pa.STYLE.get("chair_style") in ("bentwood", "light_wood", "metal_bistro", "mixed", "upholstered"):
            src = "proc:CafeChairFactory"                        # the reference's chair style (cafe r3: ABO gave upholstered chairs)
        if cat == "bar_stool" and (_pa.STYLE.get("chair_style") in ("bentwood", "light_wood", "metal_bistro", "mixed", "upholstered") or _pa.VENUE == "break-room"):
            src = "proc:CounterStoolFactory"                     # stools of the same family (style eval: cream upholstered stools)
        if cat == "beverage_fridge" and _pa.VENUE == "cafe" and os.environ.get("ROOM_DISPLAY_COOLER") != "1":    # a café's drinks fridge sits under/beside the counter; the 2 m shop
            src = "inf:BeverageFridgeFactory"                    # cooler read as a convenience store (style eval H)
        if cat == "desk_chair" and _pa.VENUE == "dental-room":   # the dentist sits on an operator stool (floor E3 r10, 3 of 3)
            src = "proc:OperatorStoolFactory"
        elif cat == "desk_chair" and self.doc.get("type") in catalog.WORK_ROOMS:   # an office task chair, not the Infinigen shell / lab
            src = "proc:TaskChairFactory"                        # stool (floors J r9, E3 r8, D3 r9)
        elif cat == "conference_chair" and self.doc.get("type") in ("meeting-room", "office", "exam-room"):   # meeting/guest/patient chairs (exam:
            # 'a bar-height shell chair on a tall stem, a drafting stool', D3 r17) from the office family,
            src = "proc:TaskChairFactory"                        # not plastic shell side chairs ('a café, not a meeting room', floor A2 r8)
            if cat == "conference_chair" and self.doc.get("type") == "meeting-room" and _pa.STYLE.get("meeting_chair_style") == "upholstered":
                src = "proc:WhiteDiningChairFactory"             # kit meeting_chair_style: upholstered side chairs in kit upholstery_srgb (B r22: 'want upholstered chairs')
            if cat == "conference_chair" and self.doc.get("type") == "meeting-room" and os.environ.get("ROOM_CONF_CHAIR_LIB") == "1":
                src = "proc:ConferenceChairFactory"              # P4: HSSD Margot white upholstered chairs (chair_lib)
        if cat == "gondola" and _pa.STYLE.get("gondola_style") == "wire":     # kit gondola_style 'wire': chrome wire shelving (the grocery market ref)
            src = "proc:WireShelfFactory"
        if cat == "wall_gondola" and _pa.STYLE.get("gondola_style") == "wire":
            src = "proc:WireWallShelfFactory"
        if cat == "cafe_chair" and _pa.STYLE.get("chair_style") == "folding":   # kit chair_style 'folding': mint folding chairs (food court)
            src = "proc:FoldingChairFactory"
        if cat == "counter" and _pa.VENUE in ("convenience", "grocery"):   # a shop till, not the café bar (floor I r11, 3 of 3)
            src = "proc:CheckoutCounterFactory"
        if cat == "break_chair" and _pa.VENUE == "break-room" and self.doc.get("area_m2", 99) < 12:   # stools only at a small pantry's
            src = "proc:CounterStoolFactory"                     # wall ledge; chairs by default -- the >=12 m2 swap missed office floor A2's
            # pantry and its standard table got counter stools (r14: 'seats level with the tabletop', 3 of 3; floor I r9 likewise)
        if cat == "break_table" and self.doc.get("type") == "break-room" and 12 <= self.doc.get("area_m2", 99) < 16:   # (a 1.2 m table
            # in H's 15.7 m2 room went mid-floor in front of the lockers, layout 6 in r41-r42, 3 of 3 each -- the round one stays)   # a small staff room's table is a
            src = "proc:CafeTableFactory"                        # café round: the 1.2 m table fell back to a wall with one chair (floor G r31)
        if cat == "break_table" and _pa.VENUE == "break-room" and self.doc.get("area_m2", 99) < 12:   # 15.7 m2 staff room needs a table (floor H r7)
            src = "proc:WindowBarFactory"                        # a small pantry gets a wall ledge (pantry r13: stools with no table)
        real_plants = bool(_pa.STYLE.get("infinigen_plants"))   # kit: the Infinigen plant container, not the procedural olive tree (G hall r37: 'unrealistic plants'); a rare native crash retries
        if cat == "floor_plant" and self.doc.get("type") in catalog.WORK_ROOMS and not real_plants:   # workplaces: the procedural olive tree too -- the grown
            src = "proc:OliveTreeFactory"                        # Infinigen plant segfaulted Blender right after placement 3 times (floors B, J, A2)
        if cat == "floor_plant" and _pa.STYLE.get("density") and _pa.VENUE == "cafe" and not real_plants:   # styled cafés: procedural olive trees (seconds,
                                                                                            # not minutes; clinic r7: not in clinics)
            src = "proc:OliveTreeFactory"
        kind, key = src.split(":")
        if kind == "abo":
            if not fr.pool(key):                                 # no ABO model passes this pool's filter: drop the item, keep the scene
                self.stats.setdefault("empty_pool", {})[key] = self.stats.get("empty_pool", {}).get(key, 0) + 1
                return None, fr.ABO_FRONT
            return fr.AboPick(key, self.rng).spawn(self.stats["furniture_added"]), fr.ABO_FRONT
        if kind == "proc":
            fac = _cls(src)(self.rng.randrange(1 << 24))
            if src in ("proc:AccentArmchairFactory", "proc:LoveseatFactory"):
                fac.rgb = tuple((_pa.STYLE.get("armchair_rgb_by_room") if src.endswith("ArmchairFactory") else _pa.STYLE.get("sofa_rgb_by_room"))[str(self.doc.get("id", ""))])
            if cat == "bed" and _pa.STYLE.get("bed_throw_by_room"):
                fac.throw_rgb = _pa.STYLE["bed_throw_by_room"].get(str(self.doc.get("id", "")))      # kit: per-room throw colour (P2b master: taupe, not teal)
            if cat == "break_table" and _pa.VENUE == "break-room" and self.doc.get("area_m2", 99) >= 12 and hasattr(fac, "L"):
                fac.H = 0.75
                if not getattr(fac, "DIMS", None):
                    fac.L = min(fac.L, 1.2)            # a 1.2 m table fits the room's middle (floor H r18: it fell back to a wall
                # ledge for two, 'the middle of the staff room empty', 3 of 3)
                # a dining-height staff table for the chairs (floor H r16: 'café chairs
                                                                 # tucked under a bar-height ledge', 2 of 3)
            if cat == "meeting_table" and self.doc.get("type") == "office":
                fac.L, fac.W = 1.2, 0.8                          # a private office's small meeting table, not a boardroom one
            if cat == "break_chair" and hasattr(fac, "style"):
                fac.style = "bentwood"                           # light_wood read as 'garden or child furniture' (floor H r31, 3 of 3);
                # flat black bistro backs at the staff table read as 'two computer
                # monitors on the table' (floor H r24-r25, 3 of 3 each)
            if cat == "locker" and self.doc.get("type") == "break-room" and 12 <= self.doc.get("area_m2", 0) < 16:
                fac.n = 2                                        # a small staff room's lockers: two doors, so the bank finds a wall with
                # its front clear of the table (floor G r34: 'the table pushed against the locker fronts', layout 6, 3 of 3)
            if cat == "waiting_bench" and getattr(_pa, "FLOOR_VENUES", ()):
                fac.n = 3                                        # floors: 3-seat rows -- 4-5 seat ones found no wall between the doors of a
                # 51 m2 lobby with doors on three walls, and it rendered with no seats at all (floor F3 r13-r14, 3 of 3)
            if cat == "medical_cabinet" and self.doc.get("type") == "exam-room":
                fac.L = 1.8                                      # a GP room's sink run is short: a 3 m run took the desk's wall now
                # that it places first (floor D3 r14: office_0-5 'no clinician workstation', 3 of 3)
            o = fac.spawn_asset(self.stats["furniture_added"])
            bpy.context.view_layer.update()
            return o, fr.INF_FRONT
        if kind == "copy":                                       # the room's own chair model, so a set matches
            protos = [o for o, _ in self.ids.values() if rd._factory(o.name) in ("ChairFactory", "BarChairFactory")]
            if protos:
                c = protos[0].copy(); c.data = protos[0].data; bpy.context.scene.collection.objects.link(c)
                c.name = f"{rd._factory(protos[0].name)}(plan).spawn_asset({self.stats['furniture_added']})"
                return c, fr.INF_FRONT
            key = "ChairFactory"
        o = self.spawn(_cls("inf:" + key))
        if cat == "balloon_sign" and o is not None and o.dimensions[1] > 1.6:   # its letters span 3-6 m: at most 1.6 m on the wall
            o.scale = o.scale * (1.6 / o.dimensions[1]); bpy.context.view_layer.update()
        return o, fr.INF_FRONT

    # ---- candidate spots per relation ---------------------------------------------------------------------------------------------
    def _along_wall(self, wid, w, d, starts=None, off=0.0):
        a, t_, n, length = self.walls[wid]
        ss = starts or [length / 2]
        out = []
        for s0 in ss:
            for k in range(0, 30):                               # slide out from the preferred spot in 15 cm steps
                s = s0 + (k + 1) // 2 * 0.15 * (1 if k % 2 else -1)
                if w / 2 + 0.05 <= s <= length - w / 2 - 0.05:
                    p = a + t_ * s + n * (d / 2 + 0.03 + off)
                    out.append((p.x, p.y, _yaw(n)))
        return out

    def spots(self, it, w, d):
        rel, tgt = it["relation"], it.get("target")
        gap = it.get("gap_m")
        # a target-less relation other than corner/center means the wall (center fell in here too until office r2: every
        # 'center' meeting table and REQUIRED_ZONE pod was stood against a wall)
        if rel in ("against_wall", "near_window") or (rel not in ("corner", "center", "near_door") and tgt not in self.ids and tgt != "room"):
            # near_door has no target and fell in here, so its entrance-door spots never ran (floor I r14-r20: the till on the same
            # side-wall spot in seven rounds, whatever the near_door code said)
            wid = it.get("wall")
            # the planned wall first, then the rest (clinic r21: the couch pinned to the door wall found no spot, twice, and the exam
            # room rendered without its exam table)
            walls = ([wid] if wid in self.walls else []) + [k for k in sorted(self.walls, key=lambda k: -self.walls[k][3]) if k != wid]
            if it.get("category") in ("office_desk", "clinic_desk") and self.doc.get("type") == "office" and self.doc.get("doors"):
                # a private office's desk at the far end, facing in: first-fit put desk, bookcase and cabinet all by the door of a
                # 2.2 x 6.2 m manager's office, the rest bare (floor F3 r20: completeness 5, 3 of 3)
                dps = [self.walls[dd["wall"]][0] + self.walls[dd["wall"]][1] * dd["at_m"] for dd in self.doc["doors"] if dd["wall"] in self.walls]
                if dps:
                    cand = [s_ for k in walls for s_ in self._along_wall(k, w, d + 2 * (gap or 0))]
                    return sorted(cand, key=lambda s_: -min((Vector((s_[0], s_[1], 0)) - Vector((p_.x, p_.y, 0))).length for p_ in dps))
            if it.get("category") == "dock_door":               # an outside wall: the hall's wall with the side rooms' doors is not one
                walls = sorted(walls, key=lambda k: sum(dd["wall"] == k for dd in self.doc.get("doors", [])))
            if it.get("avoid_windows"):                         # a WC on a solid wall, not under the window (floor H r17, 3 of 3)
                win = {w_["wall"] for w_ in self.doc.get("windows", [])}
                walls = sorted(walls, key=lambda k: k in win)
            if it.get("away_from") in self.ids:                 # the wall the target faces first (floor H r4: the basin stood on the stall
                fo = _frame(*self.ids[it["away_from"]])[1]       # wall, hidden by the end partition; restrooms put basins opposite)
                win = {w_["wall"] for w_ in self.doc.get("windows", [])}   # and no window: its mirror hangs on the wall (floor H r7)
                walls = sorted(walls, key=lambda k: (k in win, self.walls[k][2].dot(fo)))
            if it.get("near_to") in self.ids:                    # the wall nearest the target first, then the spot on it closest to the
                c_ = _frame(*self.ids[it["near_to"]])[0]          # target: a basin 'beside' an open WC found no fit and the restroom had
                def wd(k):                                        # only a toilet (floor H r9); against_wall never fails where beside does
                    a_, t_, n_, L_ = self.walls[k]
                    s_ = max(0.0, min(L_, (c_ - a_).dot(t_)))
                    return (a_ + t_ * s_ - c_).length
                walls = sorted(walls, key=wd)
                if it.get("avoid_windows"):                       # this branch re-sorted the walls by distance and lost the window preference (floor O r5: office racks 'near_to' the desk stood in front of the window)
                    win_ = {w_["wall"] for w_ in self.doc.get("windows", [])}
                    walls = [k for k in walls if k not in win_] or walls
                f_ = _frame(*self.ids[it["near_to"]])[1]
                def rel_(s):                                      # (forward, sideways) of a spot from the target
                    v = Vector((s[0], s[1], 0)) - Vector((c_.x, c_.y, 0))
                    return v.dot(f_), abs(v.dot(_left(f_)))
                cand = [s for k in walls for s in self._along_wall(k, w, d + 2 * (gap or 0))]
                dist = lambda p_: (Vector((p_[0], p_[1], 0)) - Vector((c_.x, c_.y, 0))).length
                # beside the WC's wall line first; then any wall outside its approach lane (floor G r10: the strict rule left no spot,
                # the basin was dropped and the restroom had a toilet only, 3 of 3) -- never in the lane itself (floor G r9)
                strict = sorted([s for s in cand if rel_(s)[0] < 0.3 and dist(s) >= 0.9], key=lambda p_: abs(dist(p_) - 1.1))   # standing
                # room at both: the closest spot hung the basin over the cistern (floor H r13, 3 of 3)
                loose = sorted([s for s in cand if rel_(s)[0] >= 0.3 and not (rel_(s)[0] < 1.4 and rel_(s)[1] < 0.75)], key=dist)
                return strict + loose
            if rel == "near_window" and self.doc["windows"]:
                win = self.rng.choice(self.doc["windows"])
                return self._along_wall(win["wall"], w, d, [win["at_m"]])
            cand = [(k, s) for k in walls for s in self._along_wall(k, w, d + 2 * (gap or 0))]   # gap_m: clearance kept from the wall
            if it.get("avoid_windows"):                          # A2 r19: the pantry's upper cabinets covered the window - the wall was right, the spot ON it was not: drop spots whose span crosses a window
                spans = {wd["id"]: [b for b in wd.get("blocked", []) if b[2] == "window"] for wd in self.doc.get("walls", [])}
                def clear_(k, s):
                    a_, t_, n_, L_ = self.walls[k]
                    sk = (Vector((s[0], s[1], 0)) - a_).dot(t_)
                    return not any(b0 - w / 2 - 0.05 < sk < b1 + w / 2 + 0.05 for b0, b1, _ in spans.get(k, []))
                free = [(k, s) for k, s in cand if clear_(k, s)]
                cand = free if (free or it.get("category") in HARD_AVOID_WINDOWS) else cand      # soft for most; a tall lab unit is dropped rather than stood across the window (N2 r14 LAY-01)
            return [s for _k, s in cand]
        if rel == "row" and it.get("wall") in self.walls:
            a, t_, n, length = self.walls[it["wall"]]
            k = self.row_k.get(it["id"], 0)                      # this copy's slot in the row
            cnt = max(1, it.get("count", 1))
            rg = (1.5 if it.get("category") == "cafe_table" else 0.9) if it.get("category") in TABLES else 0.2 if it.get("category") == "single_bed" else ROW_GAP   # cafe r1: tables
            # butted edge to edge read as a canteen; 0.9 m left no room for two chairs back to back between café tables -- they turned
            # sideways and collided ('long canteen rows', floor H r30: layout 6, 3 of 3)
            run = cnt * w + (cnt - 1) * rg
            g = max(0.0, it.get("gap_m") or 0.0)
            face = -n if it.get("facing") == "toward" else n
            out = []
            for shift in [0.0] + [d_ * sg for d_ in (0.3, 0.6, 1.0, 1.5, 2.0, 3.0) for sg in (1, -1)]:
                s = (length - run) / 2 + shift + k * (w + rg) + w / 2
                if w / 2 <= s <= length - w / 2:
                    p = a + t_ * s + n * (g + d / 2 + 0.03)
                    out.append((p.x, p.y, _yaw(face)))
            return out
        if rel == "near_door" and self.doc.get("doors"):         # a checkout by the entrance (shop r1: 'no checkout readable')
            glazed = {w_["wall"] for w_ in self.doc.get("windows", [])}   # the entrance is the door in the shopfront wall, not the first
            d0 = next((d_ for d_ in self.doc["doors"] if d_["wall"] in glazed), self.doc["doors"][0])   # listed (floor I r16: the till
            # stood by a staff door at the back, 'faces nothing, no front of house', 3 of 3)
            if d0["wall"] in self.walls:
                L_ = self.walls[d0["wall"]][3]
                starts = [s_ for s_ in (d0["at_m"] + d0.get("width", 1.0) / 2 + 1.0 + w / 2, d0["at_m"] - d0.get("width", 1.0) / 2 - 1.0 - w / 2)
                          if w / 2 < s_ < L_ - w / 2]
                off_ = 1.0 if it.get("category") == "counter" else 0.0   # a till stands off the wall with the cashier behind it: flush to
                # the wall between two coolers it read as 'one more display unit, no cashier space' (floor I r16-r19, 3 of 3)
                out = self._along_wall(d0["wall"], w, d, starts, off_) if starts else []
                # then the other walls, nearest the entrance first: a shopfront wall is all glazing, and 'the first 20 spots' put the till
                # by the coolers at the back (floor I r16-r17, 3 of 3)
                a0_, t0_, _, _ = self.walls[d0["wall"]]; pd = a0_ + t0_ * d0["at_m"]
                rest = [s_ for k in self.walls if k != d0["wall"]
                        for s_ in self._along_wall(k, w, d, _frange(w / 2 + 0.3, self.walls[k][3] - w / 2 - 0.3, 0.5) or None, off_)]
                return out + sorted(rest, key=lambda s_: (s_[0] - pd.x) ** 2 + (s_[1] - pd.y) ** 2)[:20]
        if it.get("category") in self.HUNG and tgt in self.ids:  # a ceiling curtain wraps its couch: centred on it, shifted into the room
            o, front = self.ids[tgt]
            c, f, tw, td = _frame(o, front)
            # the track runs 0.35 m clear of the couch's long side (clinic r9: 'the curtain runs through or over the couch')
            return [((c + f * k).x, (c + f * k).y, _yaw(f)) for k in (td / 2 + 0.2, td / 2 + 0.3, td / 2 + 0.15)]   # close along the
                    # open side (r12 'far from the couch', r17 'freestanding mid-room', r18 'missing' -- shrink keeps it here, never elsewhere)
        if rel == "center":                                     # a meeting table, an island: the middle of the room
            # the long side (local y, front +X) along the room's long axis first (critic r1: a table across the room reads as dining)
            x0, x1, y0, y1 = self.room.box
            yaws = (math.pi / 2, 0.0) if (x1 - x0) > (y1 - y0) else (0.0, math.pi / 2)
            out = [(self.centre.x + dx, self.centre.y + dy, yaw) for yaw in yaws for dx in (0, 0.4, -0.4, 0.8, -0.8)
                   for dy in (0, 0.4, -0.4)]
            if it.get("bias"):                                   # preferred shift (e.g. away from a door) tried first
                bx, by = it["bias"]
                out = [(self.centre.x + bx * k, self.centre.y + by * k, yaw) for yaw in yaws for k in (1.0, 0.6, 1.4, 0.3)] + out
            else:                                                # every centred piece may also slide away from the nearest door
                doors = [self.walls[dd["wall"]] for dd in self.doc.get("doors", []) if dd["wall"] in self.walls]
                if doors:                                        # (clinic r3: a dental chair fitted nowhere in a 3.2 m deep room)
                    n_in = min(doors, key=lambda w_: (w_[0] + w_[1] * w_[3] / 2 - self.centre).length)[2]
                    out += [(self.centre.x + n_in.x * k, self.centre.y + n_in.y * k, yaw) for yaw in yaws for k in (0.3, 0.6, 0.9)]
            gx = [x0 + w / 2 + 0.3 + 0.25 * i for i in range(int(max(0.0, (x1 - x0) - w - 0.6) / 0.25) + 1)]
            gy = [y0 + w / 2 + 0.3 + 0.25 * i for i in range(int(max(0.0, (y1 - y0) - w - 0.6) / 0.25) + 1)]
            out += sorted(((x, y, yaws[0]) for x in gx for y in gy), key=lambda s_: (s_[0] - self.centre.x) ** 2 + (s_[1] - self.centre.y) ** 2)
            # + a grid over the room for the along yaw: in an L-shaped 14 m2 room no small offset of the centre fitted it, so the table
            # went across and shrank to a desk (floor C r12-r13, 'a desk, not a meeting room', 3 of 3)
            out.sort(key=lambda s_: yaws.index(s_[2]))         # every along-axis spot before any across one: the biased across spots came
            # first, so a meeting table with its door on an end wall went across and shrank to 1.8 m (floor C r12: 'a desk', function 4-5)
            return out
        if rel == "corner" or tgt == "room":
            out = []
            n = len(self.poly)
            for i in self.rng.sample(range(n), n):
                v = Vector((*self.poly[i], 0))
                a, b = (Vector((*self.poly[i - 1], 0)) - v).normalized(), (Vector((*self.poly[(i + 1) % n], 0)) - v).normalized()
                bis = (a + b)
                if bis.length < 1e-3 or not inside((v + bis.normalized() * 0.3)[:2], self.poly):
                    continue                                     # a reflex corner: the bisector points out of the room
                for p in (v + a * (d / 2 + 0.08) + b * (w / 2 + 0.08), v + b * (d / 2 + 0.08) + a * (w / 2 + 0.08)):
                    out.append((p.x, p.y, _yaw(self.centre - p)))   # facing into the room
            return out
        o, front = self.ids[tgt]
        c, f, tw, td = _frame(o, front)
        if rel == "in_front_of":
            g = max(0.07, 0.45 if gap is None else gap)
            base = c + f * (td / 2 + g + d / 2)
            yw = _yaw(f) if it.get("face_away") else _yaw(-f)    # a counter in front of its back shelf faces the room, not the shelf
            return [((base + _left(f) * j).x, (base + _left(f) * j).y, yw) for j in (0, 0.15, -0.15, 0.3, -0.3)]
        if rel == "behind":                                      # the far side of target, facing it: the staff chair at a reception desk
            g = max(0.07, 0.25 if gap is None else gap)          # (clinic r7: the chair stood on the patients' side of the counter)
            base = c - f * (td / 2 + g + d / 2)
            offs = (0.45, -0.45, 0.0, 0.25, -0.25, 0.9, -0.9) if it.get("category") == "bar_stool" else (0, 0.25, -0.25, 0.5, -0.5)      # bar stools along a long island: two seats 0.9 m apart, then the old offsets (P2b r25: the second stool stood 1 m past the island's end)
            return [((base + _left(f) * j).x, (base + _left(f) * j).y, _yaw(f)) for j in offs]
        if rel == "beside":
            g = max(0.07, gap or 0)                              # _place keeps 5 cm between footprints
            sides = {"left": [1], "right": [-1]}.get(it.get("side"), [1, -1])
            out = []
            for sg in sides:
                for back in (-(td / 2) + d / 2, 0.0):            # backs aligned (a nightstand by a bed head), else centred
                    p = c + _left(f) * sg * (tw / 2 + g + w / 2) + f * back
                    out.append((p.x, p.y, _yaw(f)))
            return out
        if rel == "under":
            return [((c + f * (td * k)).x, (c + f * (td * k)).y, _yaw(f) + r) for k in (0.25, 0.0, 0.4) for r in (0, math.pi / 2)]
        if rel == "facing":
            out = []
            for dist in [d + (gap or 0) for d in (1.6, 2.0, 2.5, 3.0)]:   # gap_m: extra standoff (reception benches: the queue space)
                for ang in (0, 25, -25, 50, -50, 75, -75):
                    v = Vector((math.cos(_yaw(f) + math.radians(ang)), math.sin(_yaw(f) + math.radians(ang)), 0))
                    p = c + v * dist
                    out.append((p.x, p.y, _yaw(-v)))
            return out
        if rel == "around":
            # seats around EVERY copy of the target (a plan's '8 chairs around bistro' meant all 3 bistro tables; spots came from the
            # first copy only, so 2 fitted and 6 were dropped -- cafe r3), interleaved so copies fill evenly; square tables seat all 4 sides
            pitch = max(w, d) + 0.1                              # orientation-proof: w/d of an ABO chair may be swapped vs its pose
            per_copy = []
            for co, cf in getattr(self, "copies", {}).get(tgt, [self.ids[tgt]]):
                c, f, tw, td = _frame(co, cf)
                sides = []
                if abs(tw - td) < 0.25:                          # square/round: all four sides
                    sides = [(f, _left(f), td / 2, tw / 2), (_left(f), f, tw / 2, td / 2)]
                else:
                    long_f = td >= tw                            # chairs go on the long sides
                    sides = [((f, _left(f)) if long_f else (_left(f), f)) + (((td if long_f else tw) / 2, (tw if long_f else td) / 2),)]
                    sides = [(a_, b_, hl, hs) for (a_, b_, (hl, hs)) in sides]
                pts = []
                for ax, side, half_l, half_s in sides:
                    per = max(1, int((2 * half_l + 0.1) / pitch))
                    for k in range(per):
                        off = (k - (per - 1) / 2) * max(pitch, min(0.8, 2 * half_l / per))
                        for sg in (1, -1):
                            p = c + ax * off + side * sg * (half_s + d / 2 + 0.12)   # 0.07 left 2 cm after the placer's 5 cm
                            # margin and a chair's real box: every fill table 'placed, no chair fitted' (floor H r35-r39)
                            if self.CHAIR_ISSUE_GUARD and it.get("category") == "conference_chair" and not inside((p + side * sg * (d / 2 + 0.3))[:2], self.poly):
                                continue                         # the seat's tilted backrest would stand outside the room / in the window wall (O2 r12: mesh-back chairs seen through the glass); that seat is dropped
                            pts.append((p.x, p.y, _yaw(-side * sg)))
                per_copy.append(pts)
            out = [pt for grp in itertools.zip_longest(*per_copy) for pt in grp if pt is not None]
            return out
        return []

    # ---- placing --------------------------------------------------------------------------------------------------------------------
    def _balloon(self):
        """Foil letter balloons on a free wall: decoration only, so a cloth-sim failure never fails the room.

        OFF unless ROOM_BALLOON=1: Infinigen's balloon is a 166k-polygon flat-shaded cloth-sim mesh with random-letter text ('EZPRHTLZIKA')
        that renders as broken triangles (user, 2026-10-17, café H r46)."""
        if os.environ.get("ROOM_BALLOON") != "1":
            return
        try:
            self._wall_mount("balloon_sign", 2.0)
        except Exception as e:
            _log(f"balloon sign skipped: {e}")

    def _door_signs(self):
        """ROOM_DOOR_SIGNS=1, hallway rooms: a lab safety sign board beside every door on this room's walls (N r3: 'door safety signs'): on the wall plane 0.35 m past the casing on the side with more
        wall, 1.2 m above the floor, facing into the room; placed flush (no footprint check), skipped when the stretch is too short."""
        n = 0
        for dr in self.doc.get("doors", []):
            if dr.get("wall") not in self.walls:
                continue
            a_, t_, n_, L_ = self.walls[dr["wall"]]
            w_ = dr.get("width", 1.0); at = dr["at_m"]
            s = at + w_ / 2 + 0.35 if L_ - (at + w_ / 2) >= at - w_ / 2 else at - w_ / 2 - 0.35
            if not 0.3 < s < L_ - 0.3:
                continue
            o, front = self._make("door_sign")
            if o is None:
                continue
            p = a_ + t_ * s + n_ * 0.012
            o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, _yaw(n_) - math.atan2(front[1], front[0]))
            o.location = (p.x, p.y, self.room.z + 1.2)
            n += 1
        self.stats["door_signs"] = n
        _log(f"door signs: {n}")

    def _wall_mount(self, cat, z_bottom, avoid=None, only=None) -> bool:
        """A wall-mounted piece (display, whiteboard): stood against the longest free wall run (another wall than `avoid`), then lifted."""
        o, front = self._make(cat)
        if o is None:
            return False
        w, d = o.dimensions[1], o.dimensions[0]
        walls = sorted((k for k in self.walls if k != avoid and (only is None or k == only)), key=lambda k: -self.walls[k][3])
        spans = {wd["id"]: [b for b in wd.get("blocked", []) if b[2] == "window"] for wd in self.doc.get("walls", [])}
        def clear_of_windows(k, x, y):                           # clinic r2: a whiteboard hung across a window
            a_, t_, n_, L_ = self.walls[k]
            sk = (Vector((x, y, 0)) - a_).dot(t_)
            return not any(b0 - w / 2 - 0.1 < sk < b1 + w / 2 + 0.1 for b0, b1, _ in spans.get(k, []))
        high = [b for b in self.obstacles if len(b) < 6 or b[5] > z_bottom + 0.15]   # it hangs above the chairs: tested on the floor,
        # the meeting chairs round the walls blocked every spot and the room had no display or board (floor A2 r13, 3 of 3)
        for relaxed in (False, True):                            # 2nd pass (P2b r11: towel_rail failed silently in all three baths): windows no longer exclude a spot and only TALL obstacles (mirrors, cabinets above 0.9 m over the mount) block it
            hi2 = high if not relaxed else [b for b in self.obstacles if len(b) < 6 or b[5] > z_bottom + 0.9]
            for k in walls:
                if any(fr._place(o, x, y, yaw, self.room, hi2, front) for x, y, yaw in self._along_wall(k, w, d)
                       if relaxed or clear_of_windows(k, x, y)):
                    self.obstacles.append(hi2[-1])               # its wall span, for what comes after: _place recorded it in the copy
                    # only, and a bookcase then stood in front of the whiteboard (floor A2 r14: layout 5, 3 of 3)
                    o.location.z += z_bottom
                    bpy.context.view_layer.update()
                    self.stats["furniture_added"] += 1
                    if relaxed:
                        _log(f"wall_mount {cat}: placed on {k} by the relaxed retry")
                    return k
            if not relaxed:
                _log(f"wall_mount {cat}: no spot clear of windows / obstacles (walls {[(k_, round(self.walls[k_][3], 1)) for k_ in walls]}, w {w:.2f}); relaxed retry")
        _log(f"wall_mount {cat}: no spot even relaxed")
        bpy.data.objects.remove(o, do_unlink=True)
        return False

    def _clinic_walls(self):
        """Clinic fixtures on the walls, seen from every wide shot (clinic r17: signs of use median 4-5 with props only on worktops):
        3-4 of eye chart / poster / glove holder / sharps bin / towel dispenser / sanitizer, clear of windows and of each other; they
        hang above furniture, so the floor obstacles do not apply."""
        from room_planner import proc_assets as pa
        clinic_floor = any(v in ("clinic-reception", "exam-room", "dental-room", "physio-room") for v in getattr(pa, "FLOOR_VENUES", ()))
        z = {"eye_chart": 1.15, "clinic_poster": 1.25, "glove_holder": 1.25, "sharps_bin": 1.1, "towel_dispenser": 1.3, "wall_sanitizer": 1.2,
             "wall_clock": 1.9, "brochure_rack": 0.9, "grab_bar": 0.8, "hand_dryer": 1.1,
             "toilet_roll": 0.7, "waste_bin": 0.0, "cleaning_kit": 0.0, "roll_shelf": 1.3, "coat_hooks": 0.95, "baby_change": 0.6, "diagnostic_set": 1.2}   # coat_hooks: the jackets' hem (rail ~1.75 m)
        want = {"exam-room": ["eye_chart", "glove_holder", "sharps_bin", "towel_dispenser", "diagnostic_set", "clinic_poster"],
                "dental-room": ["glove_holder", "sharps_bin", "towel_dispenser", "clinic_poster"],
                "physio-room": ["clinic_poster", "wall_sanitizer", "towel_dispenser", "clinic_poster", "wall_clock"],   # exercise charts
                # on more walls (floor F3 r17: 'no anatomy or exercise charts', use 6, 3 of 3)
                "clinic-reception": ["wall_clock", "clinic_poster", "brochure_rack", "wall_sanitizer", "clinic_poster"],
                "restroom": (["grab_bar", "toilet_roll", "waste_bin", "hand_dryer", "wall_sanitizer", "roll_shelf"] +
                             (["baby_change", "clinic_poster"] if self.doc.get("area_m2", 0) >= 10 else []))   # a big WC reads empty (D3/J)
                            if clinic_floor else ["grab_bar", "toilet_roll", "waste_bin", "hand_dryer", "roll_shelf"] +   # the mop kit lives in the
                            # (no coat-hook rail: its jackets read as 'blue and red clinic pads', floor J r20, 3 of 3)
                            # stockroom: by the WC it read as 'a janitor closet' (floor H r26, 3 of 3)
                            (["clinic_poster"] if self.doc.get("area_m2", 0) >= 10 else []),   # a café/shop/office (the basin unit -- no
                            # baby-change: folded flat it is 'a blank white wall slab that reads as nothing', floor H r45, 3 of 3)
                            # -- and a big one is not 'an empty tiled room' (floor H r18)
                            # carries its own towel dispenser: a second one overlapped the mirror, floor H r17)
                            # WC: no sanitiser box or baby-change sign -- 'a clinic wall unit in a café toilet' (floor G r14, 3 of 3)
                "hallway": ["clinic_poster", "wall_sanitizer", "wall_clock", "clinic_poster", "wall_sanitizer", "clinic_poster", "brochure_rack"],
                "closet": ["coat_hooks", "coat_hooks", "clinic_poster"],   # two rails of jackets (floor F3 r19: 'one bag, no clothes', use 4-5)
                "office": ["wall_clock", "clinic_poster"],   # a clinic manager's bare walls (floor D3 r19: 'two walls blank', 3 of 3);
                # any floor office: 'a show office, nothing on the walls' (floor J r21, 3 of 3)
                "break-room": ["clinic_poster", "wall_clock"] if getattr(self, "staff_hooks", False) else [],   # no hook rail: its jackets
                # read as 'blue and red clinic pads' in a café staff room (floor H r45, 3 of 3; J r20 before)
                "utility": ["glove_holder", "towel_dispenser", "clinic_poster"] if clinic_floor else ["cleaning_kit"]}.get("utility" if str(self.doc.get("id", "")).startswith("utility")
                                                                       else self.doc.get("type"), [])   # (no wet-floor sign in a steri room, E3 r15)   # a stockroom's bare corner (floor G r17: comp 6)
        if any(rd._factory(v[0].name) == "UrinalFactory" for v in self.ids.values()):   # beside the urinals the folded baby-change
            want = [k for k in want if k != "baby_change"]      # unit read as 'a radiator against the urinal' (floor H r41, 3 of 3)
        wc = next((v[0].matrix_world.translation for v in self.ids.values() if rd._factory(v[0].name) == "ToiletFactory"), None)
        basin = next((v[0].matrix_world.translation for v in self.ids.values() if rd._factory(v[0].name) == "WashBasinFactory"), None)
        spans = {wd["id"]: [(b[0], b[1]) for b in wd.get("blocked", []) if b[2] in ("window", "door")] for wd in self.doc.get("walls", [])}
        hung, n = [], 0
        hung += [tuple(v[0].matrix_world.translation.xy) for v in self.ids.values() if rd._factory(v[0].name) == "WashBasinFactory"]
        # wall items keep off the basin's mirror and dispensers (floor H r17: 'the dispenser box covers the mirror', 3 of 3)
        seats = [v[0].matrix_world.translation.xy for v in self.ids.values() if any(k in rd._factory(v[0].name) for k in ("Chair", "Stool"))]
        if "dental-room" in (set(getattr(pa, "FLOOR_VENUES", ()) or ()) | {pa.VENUE}):      # a dental floor has no Snellen chart on any wall (E3 r29 DOM-01): a tooth-care poster instead
            want = ["clinic_poster" if k == "eye_chart" else k for k in want]
        for kind in want:
            o = pa.ClinicWallItemFactory(self.rng.randrange(1 << 24), kind).spawn_asset(self.stats["furniture_added"] + n)
            bpy.context.view_layer.update()
            w, d = o.dimensions[1], o.dimensions[0]
            cands = [(k, x, y, yaw) for k in self.walls for x, y, yaw in
                     self._along_wall(k, w, d, [self.walls[k][3] * f for f in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)])]
            # 9 spots a wall, not 4: the restroom's mop kit found none in one of H's two twin WCs and that one scored use 4-6 (r24)
            self.rng.shuffle(cands)
            if wc is not None and kind in ("grab_bar", "toilet_roll"):   # beside the WC, not across the room
                cands.sort(key=lambda c: (c[1] - wc.x) ** 2 + (c[2] - wc.y) ** 2)
            elif basin is not None and kind in ("waste_bin", "hand_dryer"):   # at the basin, where a wide shot looks (floor H r27: bin and
                cands.sort(key=lambda c: (c[1] - basin.x) ** 2 + (c[2] - basin.y) ** 2)   # dryer on far walls, 'no bin, no dryer', 3 of 3)
            ok = False
            for k, x, y, yaw in cands:
                a_, t_, n_, L_ = self.walls[k]
                sk = (Vector((x, y, 0)) - a_).dot(t_)
                if any(b0 - w / 2 - 0.1 < sk < b1 + w / 2 + 0.1 for b0, b1 in spans.get(k, [])) or any((x - hx) ** 2 + (y - hy) ** 2 < 0.6 for hx, hy in hung):
                    continue
                if any((x - q.x) ** 2 + (y - q.y) ** 2 < 0.81 for q in seats):   # clear of chairs: from eye height a bin above a lower
                    continue                                                   # backrest still sits on it (clinic r20, exam)
                if fr._place(o, x, y, yaw, self.room, self.obstacles if z[kind] < 0.3 else [], fr.INF_FRONT):   # a floor bin collides
                    o.location.z += z[kind]; bpy.context.view_layer.update()
                    # nothing tall right in front (clinic r19: a sharps bin behind a stool's backrest read as sitting on the chair)
                    fwd = Vector((math.cos(yaw), math.sin(yaw), 0)); mid = Vector((x, y, o.location.z + o.dimensions[2] / 2)) + fwd * (d + 0.02)
                    if any(self.room.scene.ray_cast(self.room.deps, mid + Vector((0, 0, dz)), fwd, distance=0.7)[0] for dz in (-0.15, 0.0)):
                        continue
                    hung.append((x, y)); n += 1; ok = True
                    break
            if not ok:
                bpy.data.objects.remove(o, do_unlink=True)
        if self.doc.get("type") == "hallway":                   # a plate beside every door, latch side (floors D3/E3/F3: 'no room signs')
            for dr in self.doc.get("doors", []):
                if dr["wall"] not in self.walls:
                    continue
                a_, t_, n_, L_ = self.walls[dr["wall"]]
                for sk in (dr["at_m"] + dr.get("width", 1.0) / 2 + 0.3, dr["at_m"] - dr.get("width", 1.0) / 2 - 0.3):
                    if 0.2 < sk < L_ - 0.2:
                        o = pa.ClinicWallItemFactory(self.rng.randrange(1 << 24), "door_sign").spawn_asset(self.stats["furniture_added"] + n)
                        bpy.context.view_layer.update()
                        p_ = a_ + t_ * sk + n_ * (o.dimensions[0] / 2 + 0.005)
                        if fr._place(o, p_.x, p_.y, math.atan2(n_.y, n_.x), self.room, [], fr.INF_FRONT):
                            o.location.z += 1.45; n += 1
                        else:
                            bpy.data.objects.remove(o, do_unlink=True)
                        break
        if self.doc.get("type") == "hallway" and clinic_floor:  # a rail along every free stretch of wall, between the doors
            for k, (a_, t_, n_, L_) in self.walls.items():
                cuts = sorted((b0 - 0.15, b1 + 0.15) for b0, b1 in spans.get(k, []))
                s0 = 0.15
                for b0, b1 in cuts + [(L_ - 0.15, L_)]:
                    if b0 - s0 >= 0.8:
                        o = pa.ClinicWallItemFactory(self.rng.randrange(1 << 24), "handrail", b0 - s0).spawn_asset(self.stats["furniture_added"] + n)
                        bpy.context.view_layer.update()
                        p_ = a_ + t_ * ((s0 + b0) / 2) + n_ * (o.dimensions[0] / 2 + 0.005)
                        if fr._place(o, p_.x, p_.y, math.atan2(n_.y, n_.x), self.room, [], fr.INF_FRONT):
                            o.location.z += 0.85; n += 1   # under the brochure rack (0.9 m)
                        else:
                            bpy.data.objects.remove(o, do_unlink=True)
                    s0 = max(s0, b1)
        self.stats["clinic_wall_items"] = n
        _log(f"clinic wall items: +{n}")
        if self.doc.get("type") == "physio-room":                # weights on a wall, towels on every bed (clinic r18: signs of use 3-4)
            beds = [fr.footprint(v[0]) for v in self.ids.values() if rd._factory(v[0].name) == "ExamTableFactory"]
            clears = [self.obstacles + [(f[0] - m, f[1] + m, f[2] - m, f[3] + m, 0, 0) for f in beds] for m in (0.8, 0.5, 0.2)] + \
                     [list(self.obstacles)]   # a therapist's -- the last step an empty list: balls through the plinth (floor F3 r8, 3/3)
            # side; 0.5 m when 0.8 leaves no wall (clinic r26: the kit was dropped)
            for F in (pa.PhysioKitFactory, pa.DumbbellRackFactory):   # + balls, rollers, bands (clinic r21: use 4); 0.8 m off every bed
                # the kit first: the rack took the last free wall (r26/r27: kit dropped twice)
                o = F(self.rng.randrange(1 << 24)).spawn_asset(self.stats["furniture_added"])   # (r25: the backrest leant into the balls)
                bpy.context.view_layer.update()
                spots = self.spots({"relation": "against_wall"}, o.dimensions[1], o.dimensions[0]); self.rng.shuffle(spots)
                # last: no reserved zones, only real collisions (r28: the gait lane + bed margins left no wall; 9 spots free without them)
                hit = next((k for k, clear in enumerate(clears) if any(fr._place(o, x, y, yaw, self.room, clear, fr.INF_FRONT) for x, y, yaw in spots)), None)
                _log(f"physio {rd._factory(o.name)}: {'step ' + str(hit) if hit is not None else 'no spot'}")
                if hit is not None:
                    self.stats["furniture_added"] += 1
                else:
                    bpy.data.objects.remove(o, do_unlink=True)
            for hid, (b, _) in list(self.ids.items()):
                if rd._factory(b.name) == "ExamTableFactory":
                    self.lived_in({"category": "towel_stack", "on": hid})
        if self.doc.get("type") == "exam-room" and "physio-room" in getattr(pa, "FLOOR_VENUES", ()):   # a physio practice's treatment
            for hid, (b, _) in list(self.ids.items()):                                                  # couches carry towels too
                if rd._factory(b.name) == "ExamTableFactory":                                           # (floor F3 r13: 'only paper
                    self.lived_in({"category": "towel_stack", "on": hid})                               # rolls', use 5-6, 3 of 3)

    def zone_workstation_pod(self, it) -> bool:
        """Bench workstations (user 2026-10-16 'an office is pods, not desks'): pods (identical) per the plan relation, a task chair at
        every seat (one chair model for the whole room), a mug or papers on some desks."""
        pod = {**it, "id": it["id"] + ":pod", "category": "pod_unit"}
        if pod.get("relation") in ("against_wall", "near_window", "row"):   # a pod seats both sides: the wall side keeps a chair + aisle
            pod["gap_m"] = max(pod.get("gap_m") or 0, 1.0)                 # (critic r1: half the bench seats had no chair)
        if not self.furniture(pod):
            return False
        for P, _ in self.copies.get(pod["id"], []):
            self._pod_chairs(P)
        self.ids.setdefault(it["id"], self.ids[pod["id"]])
        for P, _ in self.copies.get(pod["id"], []):
            for _ in range(self.rng.randint(1, 3)):
                self.lived_in({"category": self.rng.choice(("mug", "paper_stack", "small_plant")), "on": it["id"]})
        return True

    def _pod_chairs(self, P):
        """A task chair at every seat of pod P, one chair model for the whole room."""
        if getattr(self, "task_chair", None) is None:
            self.task_chair = self._make("desk_chair")
        chair0, cfront = self.task_chair
        if chair0 is None:
            return
        placed_seats = []
        if True:
            for sx, sy, syaw in P.get("seats", []):
                p = P.matrix_world @ Vector((sx, sy, 0))
                c = chair0.copy(); c.data = chair0.data; bpy.context.scene.collection.objects.link(c)
                c.name = f"{rd._factory(chair0.name)}(pod).spawn_asset({self.stats['furniture_added']})"
                yaw = P.matrix_world.to_euler().z + syaw
                out_ = P.matrix_world.to_3x3() @ Vector((math.copysign(1.0, sx), 0, 0)); out_.z = 0                   # away from the bench: a seat that collides is pulled back in steps (O5 r4: the far side of a 45-degree bench got no chairs)
                ok_ = any(fr._place(c, p.x + out_.x * dk_, p.y + out_.y * dk_, yaw, self.room, self.obstacles, cfront) for dk_ in (0.0, 0.1, 0.2, 0.35, 0.5))
                if ok_:
                    placed_seats.append((c, self.obstacles[-1]))
                    self.stats["furniture_added"] += 1
                else:
                    _log(f"pod chair dropped at ({p.x:.2f}, {p.y:.2f}) yaw {math.degrees(yaw):.0f}: collides within 0.5 m of its seat spot")
                    bpy.data.objects.remove(c, do_unlink=True)
        for c, box in placed_seats:                              # all neat first, then turned
            self._unsquare(c, cfront, box, P)
        chair0.location = (1e4, 1e4, 0)

    def zone_meeting_set(self, it) -> bool:
        """A meeting room as a set: conference table in the middle, identical chairs around, a display on one wall, a whiteboard on
        another, a speakerphone on the table."""
        tid = it["id"] + ":table"
        # size the table to the room so BOTH long sides seat: door clearance (~1.1 m) + chair zones (2 x 0.8) + aisle on the short axis;
        # a 1.3 m table in a 3.9 m deep room with a door on the long wall seated one side only (office r6: 3 chairs)
        from room_planner import proc_assets as pa
        x0, x1, y0, y1 = self.room.box
        short, long_ = sorted((x1 - x0, y1 - y0))
        W = max(1.0, min(1.3, short - 1.1 - 2 * 0.8 - 0.3))
        L = max(1.8, min(3.6, long_ - 1.5))                      # a 14 m2 room: 2.3 m, not a 1.8 m 'desk-sized table' (floor C r4, 3/3)
        L = round(L / 0.3) * 0.3
        t = pa.ConferenceTableFactory(self.rng.randrange(1 << 24), L=L, W=round(W, 2)).spawn_asset(self.stats["furniture_added"])
        bpy.context.view_layer.update()
        self.spare = getattr(self, "spare", {}); self.spare.setdefault("meeting_table", []).append((t, fr.INF_FRONT))
        # shift the table away from the nearest door along the short axis, so the door-side chairs clear the door zone (office r6)
        bias = None
        doors = [self.walls[d["wall"]][0] + self.walls[d["wall"]][1] * d["at_m"] for d in self.doc.get("doors", []) if d["wall"] in self.walls]
        if doors:
            dpt = min(doors, key=lambda p: (p - self.centre).length)
            room_short_x = (x1 - x0) < (y1 - y0)
            free = max(0.0, (short - W - 2 * 0.8 - 1.1) / 2 + 0.55)
            sgn = 1 if ((self.centre.x - dpt.x) if room_short_x else (self.centre.y - dpt.y)) > 0 else -1
            bias = (sgn * free, 0.0) if room_short_x else (0.0, sgn * free)
        n_ob = len(self.obstacles)
        if not self.furniture({"id": tid, "category": "meeting_table", "relation": "center", "bias": bias}):
            return False
        o, front = self.ids[tid]
        # a 3 m table along a 4.4 m room hit the door zone at its end, so it went ACROSS the 3.3 m room and every chair went to one side
        # (floor A2 r9: 'chairs only on the window side', both meeting rooms, 3 of 3) -- shorter until it lies along the long axis
        while True:
            f_ = fr.footprint(o)
            if ((f_[1] - f_[0]) >= (f_[3] - f_[2])) == ((x1 - x0) >= (y1 - y0)) or L <= 1.8:
                break
            del self.ids[tid]; getattr(self, "copies", {}).pop(tid, None)   # the copy list kept the removed table (A2 r10: ReferenceError)
            del self.obstacles[n_ob:]
            bpy.data.objects.remove(o, do_unlink=True)
            L = round(L - 0.6, 2)
            t = pa.ConferenceTableFactory(self.rng.randrange(1 << 24), L=L, W=round(W, 2)).spawn_asset(self.stats["furniture_added"])
            bpy.context.view_layer.update()
            self.spare["meeting_table"] = [(t, fr.INF_FRONT)]
            if not self.furniture({"id": tid, "category": "meeting_table", "relation": "center", "bias": bias}):
                return False
            o, front = self.ids[tid]
            _log(f"meeting table across the room: retried at {L} m")
        c, f, tw, td = _frame(o, front)
        seats = max(4, min(12, int(2 * max(tw, td) / 0.65)))
        self.pending_ids = set()
        self.furniture({"id": it["id"] + ":chairs", "category": "conference_chair", "relation": "around", "target": tid, "count": seats})
        wall = self._wall_mount("wall_display", 0.9)
        self._wall_mount("whiteboard", 0.9, avoid=wall)
        self.lived_in({"category": "speakerphone", "on": tid})
        for _ in range(self.rng.randint(1, 3)):
            self.lived_in({"category": self.rng.choice(("mug", "paper_stack")), "on": tid})
        self.ids.setdefault(it["id"], (o, front))
        return True

    def zone_glass_meeting_room(self, it) -> bool:
        """A glass-walled meeting room in the open office (reference: black-framed glass box with a long table, user 2026-10-16):
        two full-height glass partitions close off the corner farthest from the door, a glass door in one; the meeting set inside;
        then the box is an obstacle for everything outside."""
        from room_planner import proc_assets as pa
        x0, x1, y0, y1 = self.room.box
        doors = [self.walls[d["wall"]][0] + self.walls[d["wall"]][1] * d["at_m"] for d in self.doc.get("doors", []) if d["wall"] in self.walls]
        corners = [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]
        cx, cy, ux, uy = max(corners, key=lambda c: min(((Vector((c[0], c[1], 0)) - d).length for d in doors), default=0))
        Wb = min(4.2, (x1 - x0) * 0.4); Db = min(3.2, (y1 - y0) * 0.5)   # ~13 m2: 4.6 x 3.6 took a quarter of a 70 m2 floor (r3)
        if Wb < 3.0 or Db < 2.6:
            return False
        H = max((self.room.wall.matrix_world @ Vector(c)).z for c in self.room.wall.bound_box) - self.room.z if self.room.wall else 2.8
        # partition A runs along x at y = cy + uy*Db (door in it), partition B along y at x = cx + ux*Wb
        a = pa.GlassPartitionFactory(0, L=Wb, H=H, door_at=(Wb / 2 - 0.7) * ux * -1).spawn_asset(self.stats["furniture_added"])
        a.rotation_euler = (0, 0, math.pi / 2); a.location = (cx + ux * Wb / 2, cy + uy * Db, self.room.z)
        b = pa.GlassPartitionFactory(1, L=Db, H=H).spawn_asset(self.stats["furniture_added"] + 1)
        b.location = (cx + ux * Wb, cy + uy * Db / 2, self.room.z)
        bpy.context.view_layer.update()
        self.stats["furniture_added"] += 2
        bx = sorted((cx, cx + ux * Wb)); by = sorted((cy, cy + uy * Db))
        tid = it["id"] + ":table"
        t = self._make("meeting_table")[0]
        if t is not None:
            t.scale.y = min(1.0, (Wb - 1.6) / max(t.dimensions[1], 0.1))
            if fr._place(t, (bx[0] + bx[1]) / 2, (by[0] + by[1]) / 2, 0.0, self.room, self.obstacles, fr.INF_FRONT):
                self.ids[tid] = (t, fr.INF_FRONT); self.stats["furniture_added"] += 1
                self.pending_ids = set()
                self.furniture({"id": it["id"] + ":chairs", "category": "conference_chair", "relation": "around", "target": tid,
                                "count": max(4, min(10, int(2 * t.dimensions[1] / 0.65)))})
                self.lived_in({"category": "speakerphone", "on": tid})
            else:
                bpy.data.objects.remove(t, do_unlink=True)
        # the glass room and its walls are now off limits for the open floor
        self.obstacles.append((bx[0], bx[1], by[0], by[1], 0, 0))
        self.ids.setdefault(it["id"], (a, fr.INF_FRONT))
        self.stats["glass_rooms"] = self.stats.get("glass_rooms", 0) + 1
        return True

    def zone_pantry_run(self, it) -> bool:
        """Office pantry: a run of base + upper cabinets with sink against a wall, a microwave and coffee machine on it, a fridge beside."""
        # the run fills the longest wall (minus 0.8 m for the fridge column and 0.3 m end clearance): a fixed 2.4-3.6 m run on one short
        # wall read as a home kitchenette (office r5-r7 critics)
        from room_planner import proc_assets as pa
        # sized from the longest door-free stretch, not the longest wall (pantry r11: the longest wall held the door, the run was
        # fixed to it and placed nowhere -- an empty pantry)
        def stretch(wid):
            L_ = self.walls[wid][3]
            cuts = sorted((d["at_m"] - (d.get("width") or 1.0) / 2 - 0.3, d["at_m"] + (d.get("width") or 1.0) / 2 + 0.3)
                          for d in self.doc.get("doors", []) + self.doc.get("windows", []) if d["wall"] == wid)  # uppers cover windows
            best, s0 = 0.0, 0.0
            for c0, c1 in cuts:
                best, s0 = max(best, c0 - s0), max(s0, c1)
            return max(best, L_ - s0)
        wall = max(self.walls, key=stretch) if self.walls else None
        Lw = stretch(wall) if wall else 3.0
        Lrun = max(2.4, min(5.4, int((Lw - 0.1) / 0.6) * 0.6))  # includes the 0.7 m fridge column at its end; floored so it fits
        # rebuilt shorter in 0.6 m steps when it does not fit: scaling it down (the generic shrink) squashed the fridge column and left
        # the worktop slots outside the run (pantry r12: an espresso machine floating 1 m past the counter end)
        run = {**it, "id": it["id"] + ":run", "category": "pantry_unit", "relation": "against_wall", "wall": wall}
        placed = False
        for Lk in [Lrun - 0.6 * k for k in range(6) if Lrun - 0.6 * k >= 2.4 - 1e-6]:
            u = pa.PantryRunFactory(self.rng.randrange(1 << 24), L=round(Lk, 1)).spawn_asset(self.stats["furniture_added"])
            bpy.context.view_layer.update()
            self.spare = getattr(self, "spare", {}); self.spare["pantry_unit"] = [(u, fr.INF_FRONT)]
            if self.furniture({**run, "wall": wall if Lk == Lrun else None}):
                placed = True
                break
            for o_, _ in self.spare.pop("pantry_unit", []):       # only this run: other categories keep their spares
                self.act.tidy.delete(o_)
        if not placed:
            return False
        self.pending_ids = set()
        # the fridge column and the drinks fridge are part of the run now (pantry r9: a separate fridge ended up mid-floor)
        # appliances stand on the worktop at known slots: the generic top finder only sees the upper cabinets' top over a worktop
        # (critic r1: 'no sink, fridge or microwave visible'; both had logged 'no fit')
        R = self.ids[run["id"]][0]
        c_, f_, w_, d_ = _frame(R, fr.INF_FRONT)                  # a 1.0 m working strip in front of the run stays clear (pantry r8:
        q0, q1 = c_ + f_ * (d_ / 2 + 0.02), c_ + f_ * (d_ / 2 + 1.0)   # a table parallel to the counter left no aisle)
        sv = _left(f_) * (w_ / 2)
        xs = [q0.x + sv.x, q0.x - sv.x, q1.x + sv.x, q1.x - sv.x]; ys = [q0.y + sv.y, q0.y - sv.y, q1.y + sv.y, q1.y - sv.y]
        self.obstacles.append((min(xs), max(xs), min(ys), max(ys), 0, 0))
        L = R.dimensions[1]
        y0, Lc = -L / 2, L - 0.7                                 # cabinets y0..y0+Lc; the fridge column closes the run after it
        # items in priority order, each at the first free position (on the worktop, off the sink, 0.55 m apart): a short run keeps the
        # microwave and the coffee machine first (pantry r13: 2.4 m run, espresso dropped, critic 'no coffee machine')
        cats = ["microwave", "espresso_machine", "drink_cans", "snack_basket"] + (["drink_cans"] if Lc >= 2.6 else [])
        pos = [Lc - 0.35, Lc - 1.25, 0.25, 1.35, 1.8, Lc - 0.9, 0.2]   # 0.9 m microwave-espresso: 0.6 m fused them (pantry r10)
        slots, kept = [], []
        for cat in cats:
            yy = next((p_ for p_ in pos if 0.15 <= p_ <= Lc - 0.2 and abs(p_ - 0.75) >= 0.4 and all(abs(p_ - k) >= 0.55 for k in kept)), None)
            if yy is not None:
                kept.append(yy); slots.append((cat, y0 + yy))
        for cat, y in slots:
            y /= R.scale.y                                       # local units: a shrunk run is scaled along y
            o = self.spawn(_cls(catalog.LIVED_IN[cat]["src"]))
            if o is None:
                continue
            o.rotation_euler = R.rotation_euler.copy()           # both face local +X
            bpy.context.view_layer.update()
            if cat == "microwave" and o.dimensions.z > 0.33:     # a countertop microwave is ~0.3 m tall; Infinigen's 0.62 m one ran
                o.scale *= 0.33 / o.dimensions.z                 # into the upper cabinets (pantry r15)
                bpy.context.view_layer.update()
            f = fr.footprint(o); p = R.matrix_world @ Vector((0.0, y, 0.94))
            o.location += Vector((p.x - (f[0] + f[1]) / 2, p.y - (f[2] + f[3]) / 2, p.z - f[4]))
            bpy.context.view_layer.update()
            self.stats["lived_in_added"] = self.stats.get("lived_in_added", 0) + 1
        self.ids.setdefault(it["id"], self.ids[run["id"]])
        return True

    def zone_banquette_row(self, it) -> bool:
        """Café banquette (cafe r2: 'lounge sofas set away from the tables'): a fixed bench against a wall, 2-4 small tables in front of
        it (5 cm gap, 0.25 m apart), and a café chair facing the bench at each table."""
        b = {"id": it["id"] + ":bench", "category": "banquette", "relation": "against_wall", "wall": it.get("wall")}
        if not self.furniture(b):
            return False
        B, bf = self.ids[b["id"]]
        c, f, bw, bd = _frame(B, bf)
        n = max(2, min(4, int(bw / 0.95)))
        side = _left(f)
        placed = 0
        for k in range(n):
            o, front = self._make("cafe_table")
            if o is None:
                continue
            p = c + f * (bd / 2 + 0.05 + 0.35) + side * ((k - (n - 1) / 2) * bw / n)
            if fr._place(o, p.x, p.y, _yaw(f) + self.rng.uniform(-0.08, 0.08), self.room, self.obstacles, front):
                tid = f"{it['id']}:t{k}"
                self.ids[tid] = (o, front); self.stats["furniture_added"] += 1; placed += 1
                q = c + f * (bd / 2 + 0.05 + 0.7 + 0.35) + side * ((k - (n - 1) / 2) * bw / n)
                ch, cf = self._make("cafe_chair")
                if ch is not None and fr._place(ch, q.x, q.y, _yaw(-f), self.room, self.obstacles, cf):
                    self._unsquare(ch, cf, self.obstacles[-1], o)
                    self.stats["furniture_added"] += 1
                elif ch is not None:
                    bpy.data.objects.remove(ch, do_unlink=True)
            else:
                bpy.data.objects.remove(o, do_unlink=True)
        self.ids.setdefault(it["id"], (B, bf))
        return True

    def coffee_bar(self, it) -> bool:
        st0 = proc_assets_kit().STYLE
        if st0.get("counter_side") and st0.get("counter_side_tight_doors", True):
            orig = list(self.obstacles)                          # the kit chose this wall for the bar: tight door zones WHILE the bar is placed (H hall: 4 service doors left no 0.9 m-clear stretch), the full 0.9 m zones come back afterwards
            self._tight_door_zones(0.15)
            tight = [b for b in self.obstacles if b not in orig]
            try:
                return self._coffee_bar(it)
            finally:
                self.obstacles[:] = orig + [b for b in self.obstacles if b not in orig and b not in tight]
        return self._coffee_bar(it)

    def _coffee_bar(self, it) -> bool:
        """The service zone as one cluster (user 2026-10-16 'semantic islands'): a back-bar shelf against the wall, the counter 0.95 m in
        front of it on the same centre, an espresso machine and cake domes on the counter, the shelf stocked. Wall: it['wall'] or the
        longest free one."""
        st_ = proc_assets_kit().STYLE
        want_ = {"E": (-1, 0), "W": (1, 0), "N": (0, -1), "S": (0, 1)}.get(str(st_.get("counter_side", "")))      # kit counter_side=E|W|N|S: the bar goes on the longest wall facing that way (G r42: the reference counter runs along the EAST side)
        if want_:
            cand_ = [(w_, v_) for w_, v_ in self.walls.items() if v_[2].x * want_[0] + v_[2].y * want_[1] > 0.9 and v_[3] >= 4.0]
            if cand_:
                it = {**it, "wall": max(cand_, key=lambda c_: c_[1][3])[0]}
        if st_.get("backbar_plants"):                                                                              # kit backbar_plants=<weight>: dense greenery among the back-bar stock (G r42 'trailing greenery on the counter-wall shelves')
            self.FILL_MIX = {**self.FILL_MIX, "backbar_stock": [(s_, (float(st_["backbar_plants"]) if s_ == "abo:PLANTER" else w_)) for s_, w_ in self.FILL_MIX["backbar_stock"]]}
        sub = {"relation": "against_wall", "wall": it.get("wall")}
        back = {**sub, "id": it["id"] + ":backbar", "category": "backbar_shelf"}
        if not self.furniture(back):
            return False
        bo, bfront = self.ids[back["id"]]
        c, f, bw, bd = _frame(bo, bfront)
        ctr = {"id": it["id"] + ":counter", "category": "counter", "relation": "in_front_of", "target": back["id"], "gap_m": 0.95}
        self.pending_ids.discard(back["id"])
        if not self.furniture(ctr):
            return False
        self.fill({"on": back["id"], "category": "backbar_stock"}, _cls(catalog.LIVED_IN["backbar_stock"]["src"]))
        # bar cues (user 2026-10-16): the espresso machine always, then 4-6 of grinder / cup stacks / POS / pastry case / syrups / cakes
        # the big pieces stand at fixed counter slots (espresso at one end, pastry case at the other): the generic top finder logged
        # 'no fit' for the espresso machine and the pastry case in 2 of 6 cafes (cafe loop r1)
        C = self.ids[ctr["id"]][0]
        Lc = C.dimensions[1] / max(C.scale.y, 1e-6)
        top = max((C.matrix_world.inverted() @ (C.matrix_world @ Vector(q))).z for q in C.bound_box)
        mid_ = max(0.0, Lc / 2 - 2.0) if Lc > 3.6 else 0.0      # a long counter (kit counter_len_m): the machine and the case move in from the ends so one view sees both (S8 v10)
        sag_ = float(C.get("ir_curve_s", 0.0) or 0.0)                           # a bowed counter (kit counter_curve): x(y) = -s (2y/L)^2, heading atan(8 s y / L^2)
        for cat, y in (("espresso_machine", -Lc / 2 + 0.45 + mid_), ("pastry_case", Lc / 2 - 0.45 - mid_)):
            if cat == "pastry_case" and proc_assets_kit().STYLE.get("counter_pastry") == "integrated":
                continue                                                         # the display is part of the counter object (kit counter_pastry=integrated)
            o = self.spawn(_cls(catalog.LIVED_IN[cat]["src"]))
            if o is None:
                continue
            xc_ = -sag_ * (2 * y / Lc) ** 2; ph_ = math.atan(8 * sag_ * y / (Lc * Lc)) if sag_ else 0.0
            o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, C.matrix_world.to_euler().z + ph_ + (math.pi if cat == "espresso_machine" else 0))
            bpy.context.view_layer.update()
            f = fr.footprint(o); p = C.matrix_world @ Vector((xc_, y, top))
            o.location += Vector((p.x - (f[0] + f[1]) / 2, p.y - (f[2] + f[3]) / 2, p.z - f[4]))
            bpy.context.view_layer.update()
            self.stats["lived_in_added"] = self.stats.get("lived_in_added", 0) + 1
        # an end return from the counter to the back bar: the staff aisle closed on one side, so counter + back bar read as one bar
        # (cafe r4: the counter 0.95 m off its back bar read as 'a freestanding island mid-room', 3 of 3)
        try:
            from room_planner import proc_assets as _pa
            inv = C.matrix_world.inverted()
            xb = (inv @ (bo.matrix_world @ Vector(((min(q[0] for q in bo.bound_box) + max(q[0] for q in bo.bound_box)) / 2, 0, 0)))).x
            xs = sorted((inv @ (C.matrix_world @ Vector(q))).x for q in C.bound_box)
            x0, x1 = min(xb, xs[0]), xs[0]                       # from the back bar's centre to the counter's back face
            if x1 - x0 > 0.2:
                end = -Lc / 2 + 0.02 if self.rng.random() < 0.5 else Lc / 2 - 0.02
                ret = _pa._prims(f"CafeCounterReturnFactory({self.stats['furniture_added']}).spawn_asset(0)",
                                 [(C.data.materials[0], [("box", ((x0 + x1) / 2, end, top / 2), (x1 - x0, 0.04, top), (0, 0, 0))])])
                ret.matrix_world = C.matrix_world.copy()
                bpy.context.view_layer.update()
        except Exception as e:                                    # cosmetic: never fail the bar over it
            _log(f"counter return skipped: {e}")
        bw_ = None
        try:                                                     # the menu board goes on the BACK BAR's wall (H r66: it stood on the glazed front); a big chalkboard when the kit says menu_board_big
            bp_ = bo.matrix_world.translation
            bw_ = min(self.walls, key=lambda k_: abs((bp_ - self.walls[k_][0]).dot(self.walls[k_][2])))
        except Exception:                                        # noqa: BLE001
            bw_ = None
        self._wall_mount("menu_board", 1.5, only=bw_) or self._wall_mount("menu_board", 1.5)       # a menu on the wall (cafe r2: no café had one)
        self._balloon()                                                          # foil letter balloons over the hall (user 2026-10-17: Infinigen's sign
                                                                 # balloon generator 'might look nice')
        if "flowers" in (proc_assets_kit().STYLE.get("decor") or []):   # a big bouquet at the counter's centre (floral style eval)
            o = self.spawn(_cls("proc:FlowerArrangementFactory"))
            if o is not None:
                o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, C.matrix_world.to_euler().z)
                bpy.context.view_layer.update()
                f = fr.footprint(o); p = C.matrix_world @ Vector((-0.1, 0.0, top))
                o.location += Vector((p.x - (f[0] + f[1]) / 2, p.y - (f[2] + f[3]) / 2, p.z - f[4]))
        if proc_assets_kit().STYLE.get("fixture") == "chandelier":   # the bright focal point over the bar (floral style eval)
            ch = proc_assets_kit().ChandelierFactory(self.rng.randrange(1 << 20)).spawn_asset(self.stats["furniture_added"])
            ceil = max((self.room.wall.matrix_world @ Vector(cq)).z for cq in self.room.wall.bound_box) if self.room.wall else self.room.z + 2.8
            cc = C.matrix_world @ Vector((0.4, 0.0, 0.0))
            ch.location = (cc.x, cc.y, ceil - 0.05)
            ld = bpy.data.lights.new("ir_chandelier", "POINT"); ld.energy = 120.0; ld.color = (1.0, 0.75, 0.45); ld.shadow_soft_size = 0.3
            lo = bpy.data.objects.new("PointLampFactory(chandelier).spawn_asset(0)", ld); bpy.context.scene.collection.objects.link(lo)
            lo.location = (cc.x, cc.y, ceil - 0.5)
        bar = self.rng.sample([("grinder", self.rng.randint(1, 2)), ("cup_stack", 2), ("register", 1), ("syrup_rack", 1),
                               ("cake_dome", 2)], self.rng.randint(3, 5))
        for cat, n in bar:
            self.lived_in({"category": cat, "on": ctr["id"], "count": n})
        self.ids.setdefault(it["id"], self.ids[ctr["id"]])
        return True

    WALL_MOUNTED = {"whiteboard": 0.9, "wall_display": 0.9, "menu_board": 1.5, "wall_rail": 1.65, "wall_diagnostic": 1.3, "wall_monitor": 1.4, "towel_rail": 0.8, "notice_panel": 1.15}
    HUNG = ("privacy_curtain",)

    def _window_curtains(self):
        """One curtain pair centred on each window span of the room (P2b living: the reference has sheer curtains at its window; the spot search had no free spot there beside the media wall). The 2.4 m object is scaled
        along its width to the span + 0.6 m and stands flush on the wall, facing into the room."""
        n_ = 0
        for wd in self.doc.get("walls", []):
            if wd["id"] not in self.walls:
                continue
            a_, t_, n__, L_ = self.walls[wd["id"]]
            for b0, b1, kind in wd.get("blocked", []):
                if kind != "window":
                    continue
                o = self.spawn(_cls("proc:CurtainFactory"))
                if o is None:
                    continue
                span = max(1.0, b1 - b0) + 0.6
                o.scale.y = span / 2.4
                p = a_ + t_ * ((b0 + b1) / 2) + n__ * 0.06
                o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, math.atan2(n__.y, n__.x))
                o.location = (p.x, p.y, self.room.z)
                bpy.context.view_layer.update()
                n_ += 1
        n_ += self._bigglass_curtains()
        self.stats["window_curtains"] = self.stats.get("window_curtains", 0) + n_
        _log(f"window curtains: {n_}")

    def _bigglass_recs(self):
        """big_glass's recorded runs (scene['ir_bigglass']); the mat2 stage drops that property (S34 r11: arch blend had it, scene_mat2 did not), so when it is gone the run is rebuilt from the BigGlassPanes
        meshes standing in this room: ux along the pane run, vg its wall coordinate, the door from this room's casing on that wall."""
        from room_planner import big_glass as _bg
        recs = _bg.all_recs()
        if recs:
            return recs
        x0, x1, y0, y1 = self.room.box
        out = []
        for o in bpy.data.objects:
            if o.type != "MESH" or "BigGlassPanes" not in o.name:
                continue
            pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
            bx0, bx1, by0, by1 = min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts)
            if not (x0 - 1 < (bx0 + bx1) / 2 < x1 + 1 and y0 - 1 < (by0 + by1) / 2 < y1 + 1):
                continue
            if bx1 - bx0 >= by1 - by0:                           # a wall along x: u = x, v = y
                o0, ux, vx, ua, ub, vg, cen = Vector((0, 0, 0)), Vector((1, 0, 0)), Vector((0, 1, 0)), bx0, bx1, (by0 + by1) / 2, self.centre.y
            else:
                o0, ux, vx, ua, ub, vg, cen = Vector((0, 0, 0)), Vector((0, 1, 0)), Vector((1, 0, 0)), by0, by1, (bx0 + bx1) / 2, self.centre.x
            inw = list(vx if cen > vg else -vx)                  # the room side of the wall
            du = None
            for dr in self.doc.get("doors", []):
                if dr["wall"] in self.walls:
                    a_, t_, n_, L_ = self.walls[dr["wall"]]
                    pd = a_ + t_ * dr["at_m"]
                    if abs((pd - o0).dot(vx) - vg) < 0.7:
                        du = (pd - o0).dot(ux)
            out.append({"o0": list(o0), "ux": list(ux), "vx": list(vx), "vg": vg, "ua": ua, "ub": ub, "du": du, "inw": inw, "n_m": 2, "pitch": (ub - ua) / 2})
        return out

    def _bigglass_curtains(self):
        """BIGGLASS_CURTAIN_RGB=r,g,b: drapes on this room's big-glass run (big_glass records the run in scene['ir_bigglass']): a pair drawn back at each end of the run and one at the middle mullion,
        skipping any that would cover the door (rec['du']). Gated by auto_allow window_curtains like the window pairs."""
        raw = os.environ.get("BIGGLASS_CURTAIN_RGB")
        if not raw:
            return 0
        from room_planner import proc_home
        x0, x1, y0, y1 = self.room.box; n_ = 0
        proc_home.CurtainFactory.FORCE_RGB = tuple(float(v) for v in raw.split(","))
        try:
            for r in self._bigglass_recs():
                o0, ux, vx = Vector(r["o0"]), Vector(r["ux"]), Vector(r["vx"]); vg = r["vg"]
                c = o0 + ux * (r["ua"] + r["ub"]) / 2 + vx * vg
                if not (x0 - 1 < c.x < x1 + 1 and y0 - 1 < c.y < y1 + 1):
                    continue
                inw = Vector(r["inw"]) if r.get("inw") else (-vx if vg > 0 else vx)
                mid = r["ua"] + (r.get("n_m", 2) // 2) * r.get("pitch", (r["ub"] - r["ua"]) / 2)
                for u in (r["ua"] + 0.7, r["ub"] - 0.7, mid):
                    if r.get("du") is not None and abs(u - r["du"]) < 1.1:
                        continue
                    o = self.spawn(_cls("proc:CurtainFactory"))
                    if o is None:
                        continue
                    o.scale.y = 1.4 / 2.4
                    p = o0 + ux * u + vx * vg + inw * 0.1
                    o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, math.atan2(inw.y, inw.x))
                    o.location = (p.x, p.y, self.room.z)
                    bpy.context.view_layer.update(); n_ += 1
        finally:
            proc_home.CurtainFactory.FORCE_RGB = None
        return n_

    def _tight_door_zones(self, marg=0.15, sweep=False):
        """Replace every door's 0.9 m clearance zone (furnish_rooms.DOOR_CLEAR_M round each casing) by a tight `marg` zone: the doors themselves stay clear, the strip beside them becomes usable."""
        doors = [x for x in rd._tops() if "Door" in rd._factory(x.name)]
        doors = [x for x in doors if "Casing" in rd._factory(x.name)] or doors
        dz = fr.DOOR_CLEAR_M
        old = []
        for x in doors:
            f = fr.footprint(x); old.append((f[0] - dz, f[1] + dz, f[2] - dz, f[3] + dz))
        for x in rd._tops():                                     # a door LEAF whose mesh spans its baked swing is an obstacle too (H2 baths: a 1.8 x 1.8 m 'existing' box on a 1 m door): the swing is the layout's keep-out, not the leaf's box
            if "Door" in rd._factory(x.name) and "Casing" not in rd._factory(x.name) and x not in doors:
                f = fr.footprint(x); old.append((f[0], f[1], f[2], f[3]))
        keep = [b for b in self.obstacles if not any(all(abs(b[i] - q[i]) < 1e-3 for i in range(4)) for q in old)]
        if sweep:                                                # layout mode: any other wide box standing over a door's centre is that door's leaf / clearance in a shape the match above missed (H2 r5: a 1.8 x 1.8 m 'existing' on the bath door seen from the bedroom)
            cs_ = []
            for x in rd._tops():
                if "Door" in rd._factory(x.name):
                    f_ = fr.footprint(x); cs_.append(((f_[0] + f_[1]) / 2, (f_[2] + f_[3]) / 2))
            keep = [b for b in keep if not (max(b[1] - b[0], b[3] - b[2]) > 1.0 and any(b[0] <= cx <= b[1] and b[2] <= cy <= b[3] for cx, cy in cs_))]
            blinds_ = [fr.footprint(x) for x in rd._tops() if any(k_ in rd._factory(x.name) for k_ in ("Blind", "Curtain", "Shade"))]        # a roller blind hangs at the window: it is not a floor obstacle (H3 WC: it blocked the shower)
            keep = [b for b in keep if not any(all(abs(b[i] - q[i]) < 1e-3 for i in range(4)) for q in blinds_)]
        for x in doors:
            f = fr.footprint(x); keep.append((f[0] - marg, f[1] + marg, f[2] - marg, f[3] + marg, f[4], f[5]))
        self.obstacles[:] = keep
        _log(f"door zones tightened to {marg} m on {len(doors)} doors")

    def _forced_plants(self, want):
        """Top the room up to `want` floor plants at the first free corner / wall spots (inset 0.5 m): candidates = the four corners then every 2.5 m along each wall; a candidate is used when its footprint overlaps no existing
        object and lies on the floor (door casings are objects too, so doors stay clear)."""
        names = ("FicusPlantFactory", "LargePlantContainerFactory", "OliveTreeFactory")
        have = sum(1 for o_, _ in self.ids.values() if rd._factory(o_.name) in names)
        need = want - have
        if need <= 0:
            return
        x0, x1, y0, y1 = self.room.box
        c = [(x0 + 0.5, y0 + 0.5), (x1 - 0.5, y0 + 0.5), (x0 + 0.5, y1 - 0.5), (x1 - 0.5, y1 - 0.5)]
        for xs in range(int(x0 + 2.5), int(x1 - 1.5), 3):
            c += [(xs, y0 + 0.5), (xs, y1 - 0.5)]
        for ys in range(int(y0 + 2.5), int(y1 - 1.5), 3):
            c += [(x0 + 0.5, ys), (x1 - 0.5, ys)]
        placed = 0
        for (x, y) in c:
            if placed >= need:
                break
            boxes = [fr.footprint(o_) for o_ in rd._tops() if self.room.on_floor((fr.footprint(o_)[0] + fr.footprint(o_)[1]) / 2, (fr.footprint(o_)[2] + fr.footprint(o_)[3]) / 2)]
            if any(fr._overlap((x - 0.4, x + 0.4, y - 0.4, y + 0.4), b[:4], 0.1) for b in boxes):
                continue
            o, front = self._make("floor_plant")
            if o is None:
                continue
            if fr._place(o, x, y, 0.0, self.room, boxes, front):
                self.stats["furniture_added"] += 1; placed += 1
                self.ids[f"forced_plant{placed}"] = (o, front)
            else:
                bpy.data.objects.remove(o, do_unlink=True)
        _log(f"forced plants: have {have}, want {want}, placed {placed}")

    def _safe_furniture(self, it):
        """furniture() that never raises: one bad item (a factory with the wrong constructor, a missing attribute) is logged and counted as 'no spot' instead of killing a whole per-room round (P2 r19/r20)."""
        try:
            r = self.furniture(it)
            if r is True and it.get("category") == "curtain" and it.get("id") in self.ids:        # a curtain must END UP on a window wall: the against_wall / near_window spot search falls back to ANY wall (P2b r16: one landed on the open living|dining edge)
                o_ = self.ids[it["id"]][0]
                wins = {wd["id"] for wd in self.doc.get("walls", []) if any(b[2] == "window" for b in wd.get("blocked", []))}
                p_ = o_.matrix_world.translation
                ok_ = False
                for k_ in wins:
                    if k_ not in self.walls:
                        continue
                    a_, t_, n_, L_ = self.walls[k_]
                    if abs((p_ - a_).dot(n_)) < 0.7 and -0.3 < (p_ - a_).dot(t_) < L_ + 0.3:
                        ok_ = True
                        break
                if not ok_:
                    _log(f"furniture {it.get('id')}: curtain landed off the window walls {sorted(wins)} -> removed")
                    for k_ in [k_ for k_, v_ in self.ids.items() if v_[0] is o_]:
                        self.ids.pop(k_)
                    self.act.tidy.delete(o_)
                    return False
            return r
        except Exception as ex:                                  # noqa: BLE001
            _log(f"furniture {it.get('id')} {it.get('category')}: {ex!r}"[:200])
            self.stats["item_errors"] = self.stats.get("item_errors", 0) + 1
            return False

    def furniture(self, it) -> bool | None:
        _log(f"furniture {it.get('id')} {it['category']} {it['relation']}")
        if it["category"] == "window_bar" and proc_assets_kit().STYLE.get("window_bar_side"):       # kit window_bar_side=S|N|E|W: the ledge runs along the glazed wall on that side (H r66: the bar landed on the east wall, off the big glass)
            wnt_ = {"E": (-1, 0), "W": (1, 0), "N": (0, -1), "S": (0, 1)}.get(str(proc_assets_kit().STYLE["window_bar_side"]))
            cand_ = [(w_, v_) for w_, v_ in self.walls.items() if wnt_ and v_[2].x * wnt_[0] + v_[2].y * wnt_[1] > 0.9 and v_[3] >= 4.0]
            if cand_:
                it = {**it, "wall": max(cand_, key=lambda c_: c_[1][3])[0], "relation": "against_wall"}
        if it["category"] == "curtain":                          # curtains hang on a wall that HAS a window (P2b r15: one was placed across the open living|dining edge = a huge sheet mid-room)
            win_walls = {wd["id"]: [b for b in wd.get("blocked", []) if b[2] == "window"] for wd in self.doc.get("walls", [])}
            win_walls = {k: v for k, v in win_walls.items() if v and k in self.walls}
            if not win_walls:
                _log(f"furniture {it.get('id')}: curtain dropped (no window wall)")
                return False
            if it.get("wall") not in win_walls:
                it = {**it, "wall": max(win_walls, key=lambda k_: sum(b[1] - b[0] for b in win_walls[k_])), "relation": "against_wall"}
        if it["category"] not in catalog.FURNITURE:              # a planner / revision put a lived-in item (table_lamp) or a made-up name in `furniture` (P2 r19: KeyError killed the whole per-room round): dropped and counted
            _log(f"furniture {it.get('id')}: unknown category {it['category']!r}, dropped")
            return False
        src = catalog.FURNITURE[it["category"]]["src"]
        if src == "zone:coffee_bar":
            return self.coffee_bar(it)
        if src.startswith("zone:"):
            return getattr(self, "zone_" + src[5:])(it)
        if it["category"] in self.WALL_MOUNTED:                 # hung, not stood on the floor (r6: whiteboard at z 0.16)
            self.mounted = getattr(self, "mounted", {})
            if it["category"] == "whiteboard" and self.mounted.get("whiteboard", 0) >= 1:
                return True                                      # one board a room: the revision re-placed the planned one, and office_0-1
                # had two or three on adjacent walls, 'a training room' (floor C r11, 3 of 3)
            ok_ = bool(self._wall_mount(it["category"], self.WALL_MOUNTED[it["category"]]))
            self.mounted[it["category"]] = self.mounted.get(it["category"], 0) + ok_
            return ok_
        """True placed, False no spot, None target not placed yet."""
        tgt = it.get("target")
        if it["relation"] in ("in_front_of", "behind", "beside", "under", "facing", "around") and tgt and tgt not in self.ids \
                and tgt != "room" and tgt in self.pending_ids:
            return None
        if it["relation"] in ("around", "in_front_of", "behind") and it["category"] in SEATS and tgt and tgt != "room" \
                and tgt not in self.ids:
            return False                                         # seats whose table never placed (pantry r13/r14: stools against a bare wall;
            # floor A2 r8: a dropped off-vocabulary meeting_table's 8 chairs stood in a row along a wall, 'overflow seating', 3 of 3)
        n = 2 if it.get("side") == "both" else max(1, it.get("count", 1))
        placed = 0
        self.row_k = getattr(self, "row_k", {})
        model = None                                             # copies of one item share one model (matching chairs, one rack type)
        turn_later = []                                          # seats: all placed neat first, then turned (turning each at once
        for k in range(n):                                       # blocked the next seat's spot: 4 of 7 meeting chairs, r5)
            self.row_k[it["id"]] = k
            if model is not None and not model[0].children:
                o = model[0].copy(); o.data = model[0].data; bpy.context.scene.collection.objects.link(o)
                o.name = f"{rd._factory(model[0].name)}(copy{k}).spawn_asset({self.stats['furniture_added']})"; front = model[1]
                bpy.context.view_layer.update()
            else:
                o, front = self._make(it["category"])
            if o is None:
                return False
            w, d = (o.dimensions[1], o.dimensions[0]) if abs(front[0]) > 0.5 else (o.dimensions[0], o.dimensions[1])
            # hung pieces (a privacy curtain on a ceiling track, 0.3 m off the floor) overlap the furniture under them: no obstacle check,
            # and they block nothing (clinic r1: the curtain 'beside' the exam couch never fitted)
            zone = self.rugzones if it["category"] == "rug" else [] if it["category"] in self.HUNG else self.obstacles
            spots = self.spots(it, w, d)
            if it["category"] == "waiting_bench" and getattr(self, "staff_zones", None):
                spots = [sp for sp in spots if not any(z[0] - 0.4 < sp[0] < z[1] + 0.4 and z[2] - 0.4 < sp[1] < z[3] + 0.4 for z in self.staff_zones)]
            if it["category"] == "locker" and self.doc.get("type") not in ("closet", "restroom"):
                # its doors open over 0.8 m of floor: a spot whose clear zone already holds the staff table is no spot (floor G r22:
                # 'the table is jammed against the locker fronts', layout 5-6, 3 of 3)
                def clear_front(sp, depth):
                    fw = Vector((math.cos(sp[2]), math.sin(sp[2]), 0)); lt = Vector((-fw.y, fw.x, 0))
                    pts_ = [Vector((sp[0], sp[1], 0)) + fw * a_ + lt * b_ for a_ in (d / 2 + 0.05, d / 2 + depth) for b_ in (-w / 2, w / 2)]
                    box = (min(q.x for q in pts_), max(q.x for q in pts_), min(q.y for q in pts_), max(q.y for q in pts_))
                    return not any(fr._overlap(box, b, 0.0) for b in self.obstacles)
                # 0.8 m first, then 0.45 m, then any wall: a strict-only filter dropped the lockers of a 14 m2 staff room (floor G r23)
                small_ = self.doc.get("type") == "break-room" and self.doc.get("area_m2", 0) < 16
                spots = [sp for sp in spots if clear_front(sp, 0.8)] or [sp for sp in spots if not small_ and clear_front(sp, 0.45)] or \
                    ([] if self.doc.get("type") == "break-room" and self.doc.get("area_m2", 0) < 16 else spots)   # a small staff room
                # rather loses its lockers (its coat hooks stay) than sets them against the table (floor G r34-r35, layout 6, 3 of 3 each)
            pose = it.get("pose", "aligned")
            if pose == "aligned" and it["category"] in SEATS:
                pose = "natural"                                 # user 2026-10-16: chairs in neat rows look staged
            if pose == "pulled_out" and it["relation"] not in ("around", "in_front_of"):
                pose = "angled"                                  # pulled out from a wall = into it
            # the neat spot is the fallback; a seat tries 4 random natural poses per spot first (one try per spot left most chairs
            # neat: a turned chair's box hit its neighbour and the neat spot won)
            natural = pose == "natural"
            spots = spots if natural else [self._posed(x, y, yaw, pose) for x, y, yaw in spots] + spots
            if any(fr._place(o, x, y, yaw, self.room, zone, front) for x, y, yaw in spots):
                if natural:
                    turn_later.append((o, front, self.obstacles[-1]))
                model = model or (o, front)
                placed += 1
                self.stats["furniture_added"] += 1
                self.ids.setdefault(it["id"], (o, front))
                self.copies = getattr(self, "copies", {})
                self.copies.setdefault(it["id"], []).append((o, front))   # a `row` of racks is one id: fill must reach every copy
                if it["category"] == "reception_desk":            # the staff side stays staff: waiting benches stood right behind the
                    c_, f_, w_, d_ = _frame(o, front)            # counter (floor F3 r18, 'the receptionist has nowhere to sit', 2 of 3)
                    q0, q1 = c_ - f_ * (d_ / 2), c_ - f_ * (d_ / 2 + 1.2)
                    sv = _left(f_) * (w_ / 2 + 0.3)
                    xs = [q0.x + sv.x, q0.x - sv.x, q1.x + sv.x, q1.x - sv.x]; ys = [q0.y + sv.y, q0.y - sv.y, q1.y + sv.y, q1.y - sv.y]
                    self.staff_zones = getattr(self, "staff_zones", []) + [(min(xs), max(xs), min(ys), max(ys))]   # benches keep out
                if it["category"] == "locker" and self.doc.get("type") not in ("closet", "restroom"):   # its doors open: 0.8 m clear in front (floor H r13-r15: 'the table
                    # -- not in a changing room, whose bench belongs there (floor F3 r11: bench dropped)
                    c_, f_, w_, d_ = _frame(o, front)            # blocks the locker doors', 3 of 3)
                    q0, q1 = c_ + f_ * (d_ / 2), c_ + f_ * (d_ / 2 + 0.8)
                    sv = _left(f_) * (w_ / 2)
                    xs = [q0.x + sv.x, q0.x - sv.x, q1.x + sv.x, q1.x - sv.x]; ys = [q0.y + sv.y, q0.y - sv.y, q1.y + sv.y, q1.y - sv.y]
                    self.obstacles.append((min(xs), max(xs), min(ys), max(ys), 0, 0))
            elif (it["category"] in SHRINKABLE and self._shrink_place(o, front, it, zone)) or (it["category"] == "bed" and self._shrink_bed(o, front, it, zone)) or (RELAX_ZONES and it["category"] in RELAX_CATS and self._shrink_bed(o, front, it, zone, relax=True)) or (
                    # a free-standing table whose planned relation fits nowhere goes to the middle of the room (office r2: the break
                    # table 'in_front_of' the pantry run failed twice and the pantry had no table)
                    it["category"] in TABLES and it["category"] != "workbench" and it["relation"] != "center" and any(   # a bench is a wall
                        # piece: without a wall spot it is dropped (wh r22: the third bench fell back to mid-floor)
                        fr._place(o, x, y, yaw, self.room, zone, front) for x, y, yaw in self.spots({**it, "relation": "center"}, w, d))):
                placed += 1
                self.stats["furniture_added"] += 1
                self.ids.setdefault(it["id"], (o, front))
                self.copies = getattr(self, "copies", {})
                self.copies.setdefault(it["id"], []).append((o, front))
            else:
                # Keep it for the next item of this category: an Infinigen plant takes 4-5 min to grow (2026-10-15). Leftovers go at
                # the end of the room (drop_spares).
                o.location = (1e4, 1e4, 0)
                self.spare = getattr(self, "spare", {})
                self.spare.setdefault(it["category"], []).append((o, front))
                break
        if it["category"] == "parallel_bars" and placed:          # a clear gait lane round the bars, before anything else is placed
            for o_, _ in self.copies.get(it["id"], []):
                f = fr.footprint(o_)
                self.obstacles.append((f[0] - 1.0, f[1] + 1.0, f[2] - 1.0, f[3] + 1.0, 0, 0))
        host = self.ids.get(it.get("target"), (None,))[0]
        for o_, f_, box in turn_later:
            self._unsquare(o_, f_, box, host)
        if not placed and it["category"] == "desk_chair" and it.get("relation") == "behind" and it.get("target") in self.ids:
            # no floor between desk and wall: the chair at the desk's other side, never no chair (floor F3 r15: a manager's office with
            # 'a desk and no chair', function 5-6, 3 of 3)
            return self.furniture({**it, "relation": "in_front_of"})
        if not placed and it["category"] == "conference_chair" and it.get("relation") == "in_front_of" and it.get("target") in self.ids \
                and rd._factory(self.ids[it["target"]][0].name) in ("OfficeDeskFactory", "ClinicDeskFactory"):
            # a narrow office has no depth for a guest in front of a desk kept 1.05 m off the wall: at its end instead (floors D3 r21 /
            # F3 r20: 'no visitor chair', manager completeness 5, 3 of 3 each)
            return self.furniture({**it, "relation": "beside", "count": 1})
        return placed > 0

    def _shrink_bed(self, o, front, it, zone, relax=False) -> bool:
        """P2 r3-r5: a bed found no spot in 2.2-3.7 m bedrooms although the spot search returned 24-60 candidates: every one overlapped the DOOR ZONES
        (furnish_rooms.obstacles: each door casing + DOOR_CLEAR_M = 0.9 m on every side, so two doors in a 2.2 m room cover it). Beds therefore try
        again with those zones cut to 0.4 m round the casing (an open leaf parks against the wall; the foot of the bed may stand where the leaf swings),
        at full size, x0.88 and x0.78 of the ORIGINAL scale (a retried spare used to shrink again every time: 1.06 m beds)."""
        s0 = o.get("ir_scale0") or tuple(o.scale)
        o["ir_scale0"] = s0
        doors = [x for x in rd._tops() if "Door" in rd._factory(x.name)]
        doors = [x for x in doors if "Casing" in rd._factory(x.name)] or doors
        dz = fr.DOOR_CLEAR_M
        old = []
        for x in doors:
            f = fr.footprint(x); old.append((f[0] - dz, f[1] + dz, f[2] - dz, f[3] + dz))
        keep = [b for b in zone if not any(all(abs(b[i] - q[i]) < 1e-3 for i in range(4)) for q in old)]
        for dr in self.doc.get("doors", []):                     # the realizer's own door-swing box (RoomRealizer.__init__, utility / closet / kitchen / office rooms): P2 r10 study, the '?' box
            if dr["wall"] not in self.walls:                     # 1.1 x 1.4 m beside a leaf that is already baked open 0.7 m into the room
                continue
            a_, t_, n_, L_ = self.walls[dr["wall"]]
            w_ = dr.get("width", 1.0); c_ = a_ + t_ * dr["at_m"]
            pts = [c_ + t_ * sg * (w_ / 2 + 0.1) + n_ * dd for sg in (1, -1) for dd in (0.0, min(w_, 1.0) + 0.1)]
            q = (min(v.x for v in pts), max(v.x for v in pts), min(v.y for v in pts), max(v.y for v in pts))
            keep = [b for b in keep if not all(abs(b[i] - q[i]) < 1e-3 for i in range(4))]
        # P2 r6: a 2.23 m wide bedroom with doors on two walls still refused every try (bed 1.76 + two 0.4 m zones = 2.56 m): a second pass cuts the zones to the casing + 5 cm
        for marg in (0.4, 0.05):
            tall = o.dimensions[2] * s0[2] / max(o.scale[2], 1e-6) > 1.5     # a tall run / rack keeps a 0.9 m passage in front of every doorway (P2 r12 LAY-01: the kitchen run stood in the doorway); beds, desks, chairs may use the cut zone
            def _zone(x, marg=marg, tall=tall):
                f_ = fr.footprint(x)
                if not tall:
                    return (f_[0] - marg, f_[1] + marg, f_[2] - marg, f_[3] + marg, f_[4], f_[5])
                if f_[1] - f_[0] < f_[3] - f_[2]:                             # a casing is thin across the wall: pad 0.9 m into the room, only  along the wall
                    return (f_[0] - 0.9, f_[1] + 0.9, f_[2] - marg, f_[3] + marg, f_[4], f_[5])
                return (f_[0] - marg, f_[1] + marg, f_[2] - 0.9, f_[3] + 0.9, f_[4], f_[5])
            z2 = keep + [_zone(x) for x in doors]
            for k in ((1.0, 0.85, 0.7) if relax else (1.0, 0.88, 0.78) if marg > 0.1 else (0.88, 0.78, 0.7)):
                o.scale = (s0[0] * k, s0[1] * k, s0[2] * k)
                bpy.context.view_layer.update()
                w, d = (o.dimensions[1], o.dimensions[0]) if abs(front[0]) > 0.5 else (o.dimensions[0], o.dimensions[1])
                for rel in (("orig",) if it["category"] == "rug" else ("orig", "against_wall", "corner", "dense")):   # 'orig' = the plan's own relation (rug 'under' the bed, chair 'behind' the desk) with the cut zones
                    if rel == "orig":
                        sp_ = self.spots(it, w, d)
                    elif rel == "dense":                                       # every 10 cm along every wall: the standard spot list skipped the one free stretch (P2 r9 bedroom_0/2: free at x 3.7-4.1 with only the doors as obstacles)
                        sp_ = [(p.x, p.y, _yaw(n_)) for a_, t_, n_, L_ in self.walls.values() for s_ in [w / 2 + 0.1 * i for i in range(max(0, int((L_ - w) / 0.1) + 1))]
                               for p in [a_ + t_ * s_ + n_ * (d / 2 + 0.03)]]
                    else:
                        sp_ = self.spots({**it, "relation": rel}, w, d)
                    _log(f"bed shrink x{k} zone {marg}: {rel} {len(sp_)} spots for {w:.2f}x{d:.2f} m, {len(zone)} -> {len(z2)} obstacles ({len(doors)} door zones cut)")
                    hits, n_try, orig, hit_now, n_off = {}, 0, fr._overlap, [False], 0
                    def rec(a, b, m=0.05, _o=orig, _h=hits):               # which obstacle boxes refuse the spots (diagnostics)
                        r = _o(a, b, m)
                        if r:
                            hit_now[0] = True
                            _h[tuple(round(v, 2) for v in b[:4])] = _h.get(tuple(round(v, 2) for v in b[:4]), 0) + 1
                        return r
                    fr._overlap = rec
                    try:
                        for x, y, yaw in sp_:
                            n_try += 1; hit_now[0] = False
                            if fr._place(o, x, y, yaw, self.room, z2, front):
                                zone.append(z2[-1])
                                self.stats["bed_shrunk"] = self.stats.get("bed_shrunk", 0) + 1
                                return True
                            n_off += not hit_now[0]                          # refused without touching any obstacle = off the floor mesh
                    finally:
                        fr._overlap = orig
                    if sp_ and marg < 0.1 and k == 0.7:
                        names = {}
                        for x_ in rd._tops():                              # which object owns a refusing box (P2 r8: a 1.1 x 1.4 m box in a 5 m2 study matched no door/furniture)
                            try:
                                f_ = fr.footprint(x_)
                            except Exception:                              # noqa: BLE001
                                continue
                            names[tuple(round(v, 2) for v in f_[:4])] = x_.name.split("(")[0]
                        top = [(kv[0], kv[1], names.get(kv[0], "?")) for kv in sorted(hits.items(), key=lambda kv: -kv[1])[:14]]
                        _log(f"relaxed place {it['category']} {w:.2f}x{d:.2f}: {n_try} spots, {n_off} refused off-floor (no obstacle touched), obstacle hits {top}, room box {tuple(round(v, 2) for v in self.room.box)}")
        return False

    def _shrink_place(self, o, front, it, zone) -> bool:
        """A long counter / shelf that fits nowhere is shortened (x0.75 along its length, down to 1.4 m) and tried again: a 3.2 m
        counter on a 3.8 m wall with a door zone failed in 3 of 5 cafes (2026-10-16), and the spare reuse kept retrying it unchanged."""
        lmin = 1.0 if it["category"] in ("storage_rack", "stock_shelf", "supply_shelf", "prep_table") else 1.4  # a stockroom rack can be a 1-1.4 m bay (floor I r6: 2 racks unplaced
        while o.dimensions[1] * 0.75 >= lmin:                    # in a 15.8 m2 stockroom with a door and a window)
            o.scale.y *= 0.75
            bpy.context.view_layer.update()
            w, d = (o.dimensions[1], o.dimensions[0]) if abs(front[0]) > 0.5 else (o.dimensions[0], o.dimensions[1])
            if any(fr._place(o, x, y, yaw, self.room, zone, front) for x, y, yaw in self.spots(it, w, d)):
                self.stats["shrunk"] = self.stats.get("shrunk", 0) + 1
                return True
        return False

    def _drop_orphan_chairs(self):
        """A café chair more than 0.8 m from every table, bench, counter or ledge is removed (floors G r26 / H r27: 'chairs loose on the
        open floor, facing no table', layout 6, 3 of 3 each)."""
        tops = rd._tops()
        tabs = [fr.footprint(o) for o in tops if any(k in rd._factory(o.name) for k in ("Table", "Banquette", "Counter", "Bar"))]
        n = 0
        for o in [o for o in tops if rd._factory(o.name) in ("CafeChairFactory", "AboCafechairFactory", "AboChairFactory")]:      # ABO café chairs too (S7 r10: loose chairs mid-café)
            x, y = o.matrix_world.translation.x, o.matrix_world.translation.y
            if not self.room.on_floor(x, y):
                continue
            gap = min((math.hypot(max(f[0] - x, 0, x - f[1]), max(f[2] - y, 0, y - f[3])) for f in tabs), default=99)
            if gap > 0.8:
                for k in [k for k, v in self.ids.items() if v[0] is o]:
                    self.ids.pop(k)
                for k, v in getattr(self, "copies", {}).items():
                    v[:] = [c for c in v if c[0] is not o]
                self.act.tidy.delete(o); n += 1
        self.stats["orphan_chairs"] = self.stats.get("orphan_chairs", 0) + n
        _log(f"orphan café chairs removed: {n}")

    def _drop_orphan_dining_chairs(self):
        """P2 r18 LAY-02: a row of dining chairs along the wall with no table (the planned table failed / sits elsewhere): any dining chair (not office, desk or armchair) over 0.9 m from every
        dining table top is removed."""
        tops = rd._tops()
        tabs = [fr.footprint(o) for o in tops if "TableDining" in rd._factory(o.name)]
        if not tabs:
            return
        n = 0
        for o in [o for o in tops if "Chair" in rd._factory(o.name) and not any(k in rd._factory(o.name) for k in ("Office", "Desk", "Arm", "Cafe", "Lounge"))]:
            x, y = o.matrix_world.translation.x, o.matrix_world.translation.y
            if not self.room.on_floor(x, y):
                continue
            if min(math.hypot(max(f[0] - x, 0, x - f[1]), max(f[2] - y, 0, y - f[3])) for f in tabs) > 0.9:
                for k in [k for k, v in self.ids.items() if v[0] is o]:
                    self.ids.pop(k)
                for k, v in getattr(self, "copies", {}).items():
                    v[:] = [c for c in v if c[0] is not o]
                self.act.tidy.delete(o); n += 1
        self.stats["orphan_dining_chairs"] = self.stats.get("orphan_dining_chairs", 0) + n
        _log(f"orphan dining chairs removed: {n}")

    def drop_spares(self):
        for objs in getattr(self, "spare", {}).values():
            for o, _ in objs:
                self.act.tidy.delete(o)
        self.spare = {}

    def _posed(self, x, y, yaw, pose):
        """(x, y, yaw) moved out of square: angled turns it, pulled_out also moves it back along its facing (away from its target)."""
        sgn = self.rng.choice((-1, 1))
        if pose == "angled":
            return x, y, yaw + sgn * math.radians(self.rng.uniform(8, 20))
        if pose == "pulled_out":
            d = self.rng.uniform(0.15, 0.35)
            return x - math.cos(yaw) * d, y - math.sin(yaw) * d, yaw + sgn * math.radians(self.rng.uniform(10, 25))
        if pose in ("natural", "natural_small", "natural_mid", "natural_big"):
            # a used seat (user 2026-10-16: 'why do the chairs always face one place?'): small / medium / big turns, the big ones
            # sideways or turned right round and rolled out from the desk -- someone just got up
            cls = pose[8:] if pose != "natural" else self.rng.choices(("small", "mid", "big"), (0.35, 0.30, 0.35))[0]
            ang = {"small": (5, 25), "mid": (25, 70), "big": (70, 180)}[cls]
            ang = self.rng.uniform(*ang)
            d = self.rng.uniform(0.3, 0.6) if cls == "big" else self.rng.uniform(0.05, 0.25 if cls == "mid" else 0.15) if self.rng.random() < 0.6 else 0.0
            # (0.1-0.4 m: a guest chair stood 1.4 m off the desk front, 'two task chairs alone mid-floor' -- floor J r25-r27, 3 of 3)
            return x - math.cos(yaw) * d, y - math.sin(yaw) * d, yaw + sgn * math.radians(ang)
        return x, y, yaw

    def _unsquare(self, o, front, own=None, host=None):
        """A seat that already stands neat is turned (and often pulled back) in place, kept only if clear. Placing neat first keeps
        every seat; turning first cost half the chairs, because a turned chair's box hit its neighbour (user 2026-10-16: 'chairs all
        facing one way look awkward, rotate them randomly')."""
        # called right after a successful fr._place, which appended this seat's box last; fr.footprint(o) differs from that box in z,
        # so looking it up by value never matched and every turn hit the seat's own box (r5: 0 of 7 chairs turned)
        f0 = own if own is not None else self.obstacles[-1]
        self.obstacles.remove(f0)
        m0 = o.matrix_world.copy()
        loc0, rz0 = o.location.copy(), o.rotation_euler.z
        fwd = m0.to_3x3() @ Vector((*front, 0)); fwd.z = 0; fwd.normalize()
        hb = fr.footprint(host) if host is not None else None
        w_ = (0.0, 0.1, 0.9) if self.doc.get("type") in ("open-office", "office", "meeting-room", "exam-room", "clinic-reception", "cafe",
                                                         "break-room") \
            else (0.35, 0.30, 0.35)   # work rooms: no big turns -- 'task chairs drift into the aisles at random angles' (A2 r11, C r9, 3/3)
        # and few mid ones: at 35% mid (25-70 deg, pulled 0.1-0.4 m) they still 'stood in the aisles facing sideways' (A2 r12: layout 5, 3/3)
        cls = self.rng.choices(("big", "mid", "small"), w_)[0]
        order = {"big": ("big", "big", "big", "mid", "mid", "small"), "mid": ("mid", "mid", "mid", "small", "small", "small"),
                 "small": ("small",) * 6}[cls]                  # the drawn class first, then smaller turns before neat
        for c_ in order:
            x, y, yaw = self._posed(loc0.x, loc0.y, _yaw(fwd), "natural_" + c_)
            o.location.x, o.location.y = x, y
            o.rotation_euler.z = rz0 + (yaw - _yaw(fwd))
            bpy.context.view_layer.update()
            f = fr.footprint(o)
            cs = [(f[0] + 0.05, f[2] + 0.05), (f[1] - 0.05, f[2] + 0.05), (f[0] + 0.05, f[3] - 0.05), (f[1] - 0.05, f[3] - 0.05)]
            # seats may overlap 8 cm box-to-box (a turned chair's box is far bigger than the chair; with the normal 5 cm margin every
            # turn in a tight row hit a neighbour and the row stayed at 0 deg)
            # its own table/desk may overlap 20 cm (a chair tucks under the top; with 5 cm every turn at a table was refused)
            seats = getattr(self, "seat_boxes", set())
            def margin(b):
                if hb is not None and all(abs(b[i] - hb[i]) < 0.03 for i in range(4)):
                    return -0.2
                return -0.08 if b in seats else 0.05
            if all(self.room.on_floor(cx, cy) for cx, cy in cs) and \
                    not any(fr._overlap(f, b, margin(b)) for b in self.obstacles):
                self.obstacles.append(f)
                self.seat_boxes = seats | {f}
                self.stats["seats_turned"] = self.stats.get("seats_turned", 0) + 1
                return True
        o.location, o.rotation_euler.z = loc0, rz0
        bpy.context.view_layer.update()
        self.obstacles.append(f0)
        self.seat_boxes = getattr(self, "seat_boxes", set()) | {f0}
        return False

    def adjust(self, it):
        """Turn or pull out an existing piece in place; kept only if it still stands on the floor clear of everything else."""
        if it["id"] not in self.ids:
            return
        o = self.ids[it["id"]][0]
        f0 = fr.footprint(o)
        if f0 in self.obstacles:
            self.obstacles.remove(f0)
        m0 = o.matrix_world.copy()
        fwd = o.matrix_world.to_3x3() @ Vector((*fr.INF_FRONT, 0)); fwd.z = 0; fwd.normalize()   # existing pieces are Infinigen
        x, y, yaw = self._posed(o.location.x, o.location.y, _yaw(fwd), it["pose"])
        o.location.x, o.location.y = x, y
        o.rotation_euler.z += yaw - _yaw(fwd)
        bpy.context.view_layer.update()
        f = fr.footprint(o)
        corners = [(f[0] + 0.05, f[2] + 0.05), (f[1] - 0.05, f[2] + 0.05), (f[0] + 0.05, f[3] - 0.05), (f[1] - 0.05, f[3] - 0.05)]
        if all(self.room.on_floor(cx, cy) for cx, cy in corners) and not any(fr._overlap(f, b) for b in self.obstacles):
            self.obstacles.append(f); self.stats["adjusted"] += 1
        else:
            o.matrix_world = m0; bpy.context.view_layer.update(); self.obstacles.append(f0)

    def _near_spots(self, tgt, w, d):
        """Floor spots around an object: the shirt by the bed, the basket next to the dresser."""
        o, front = self.ids[tgt]
        c, f, tw, td = _frame(o, front)
        out = []
        for ang in self.rng.sample(range(0, 360, 30), 12):
            v = Vector((math.cos(math.radians(ang)), math.sin(math.radians(ang)), 0))
            for k in (0.15, 0.35, 0.6):
                p = c + v * (max(tw, td) / 2 + max(w, d) / 2 + k)
                out.append((p.x, p.y, self.rng.uniform(-math.pi, math.pi)))
        return out

    def _spawn_cached(self, cls):
        """ROOM_FILL_PROTOS=K (default 0 = off): a stocked rack spawns at most K real objects per product class and fills the rest with LINKED COPIES of them (shared mesh and materials, only the transform
        differs). Spawning a fresh Infinigen / procedural product per item took ~5 h for the M market's racks (r12: 'fill rack_w2_left (cafe_stock): 104 items'). Returns (object, is_new)."""
        K = int(os.environ.get("ROOM_FILL_PROTOS", "0") or 0) or (6 if getattr(cls, "__name__", "") == "BookStackFactory" else 0)
        if K <= 0 and os.environ.get("ROOM_RACK_FULL") == "1":     # perf (N2 r23: 487 rack items took 6,400 s, ~13 s each at load 110): every spawn ends in a scene-wide view_layer.update(); 8 real prototypes per class, the rest linked copies
            K = 8      # a book stack is the slowest item to build (O3 r1: 104 stacks = 3.5 h): always share 6 prototypes
        if K <= 0:
            return self.spawn(cls), True
        pool = self.__dict__.setdefault("_fill_protos", {}).setdefault(cls, [])
        pool[:] = [n_ for n_ in pool if n_ in bpy.data.objects]                  # pool holds object NAMES: a prototype that was deleted (no room) is gone
        if len(pool) < K:
            o = self.spawn(cls)
            if o is not None and o.type == "MESH" and not o.children and not o.modifiers:
                pool.append(o.name)
            return o, True
        src = bpy.data.objects[self.rng.choice(pool)]
        o = src.copy()                                                            # linked duplicate: o.data is src.data
        for c_ in src.users_collection:
            c_.objects.link(o)
        return o, False

    def _item(self, cls, F, s, pose):
        """One small item on support s of F (lying if asked); returns it or None."""
        o, new_ = self._spawn_cached(cls)
        if o is not None and new_:
            _shelf_labels(o, self.rng)                           # printed packaging on any shelf, not only the shop's facings
        if o is None:
            return None
        if self.act.try_place(o, F, s, self.rng, "any", yaw_sigma=math.radians(25) * (1 - self.t) + 0.05, lie=pose == "lying"):
            self.stats["placed"][cls.__name__] = self.stats["placed"].get(cls.__name__, 0) + 1
            return o
        self.act.tidy.delete(o); self.stats["no_room"] += 1
        return None

    def _drop_on(self, cls, host, pose, cat):
        """Hold the item just above the host's top at a seat-like spot and let settle() drop it (deleted if it does not stay)."""
        o = self.spawn(cls)
        if o is None:
            return
        F, front = host
        c, f, tw, td = _frame(F, front)
        if "Bed" in F.name:                                      # Infinigen bed front (+x) is the foot: cushions at the head
            at = c - f * td * 0.3 if cat == "cushion" else c + f * td * self.rng.uniform(0.0, 0.3)
        else:
            at = c + f * td * 0.15                               # in front of the backrest
        at += _left(f) * self.rng.uniform(-0.3, 0.3) * tw
        top = fr.footprint(F)[5]
        hit = bpy.context.scene.ray_cast(bpy.context.evaluated_depsgraph_get(), Vector((at.x, at.y, top + 0.01)), Vector((0, 0, -1)),
                                         distance=top + 0.01 - self.room.z)
        if not hit[0] or hit[1].z < self.room.z + 0.15:          # nothing to sit on at that spot
            self.act.tidy.delete(o); self.stats["no_room"] += 1
            print(f"[lived] {cat} on {rd._factory(F.name)}: no seat under drop point", flush=True)
            return
        bpy.context.view_layer.update()
        fo = fr.footprint(o)
        o.location += Vector((at.x - (fo[0] + fo[1]) / 2, at.y - (fo[2] + fo[3]) / 2, hit[1].z + 0.03 - fo[4]))
        bpy.context.view_layer.update()
        self.toss.append((o, host, pose, True))
        self.stats["placed"][cls.__name__] = self.stats["placed"].get(cls.__name__, 0) + 1
        print(f"[lived] {cat} on {rd._factory(F.name)} ({pose}): dropped", flush=True)

    # warehouse stock is cartons (warehouse r4: 'cosmetic jars and candles on steel racks' -- the ABO BOX pool is decor boxes)
    FILL_MIX = {"cardboard_box": [("proc:CardboardBoxFactory", 6), ("proc:PlasticBinFactory", 2), ("inf:FoodBoxFactory", 0.5)],
                "storage_bin": [("proc:PlasticBinFactory", 5), ("proc:CardboardBoxFactory", 2)],
                "cafe_stock": [("proc:CafeStockFactory", 3), ("inf:FoodBoxFactory", 2), ("inf:JarFactory", 1.5), ("inf:BottleFactory", 1.5),
                               ("inf:FoodBagFactory", 1)],   # labelled goods beside the bean bags: CafeStock / DryGoods alone read as 'toy
                               # blocks, unlabelled jars, pill-shaped sacks' (floor H r45 stockroom surface realism 4, 3 of 3)
                # 40% cups/mugs, 20% coffee bags + equipment, 15% jars/bottles, 15% food, 10% plants (user 2026-10-16)
                "backbar_stock": [("inf:CupFactory", 3), ("proc:CupStackFactory", 1), ("inf:FoodBoxFactory", 1.5), ("proc:GrinderFactory", 0.5),
                                  ("inf:JarFactory", 1), ("inf:BottleFactory", 0.5), ("inf:BowlFactory", 1.5), ("abo:PLANTER", 1)],
                # varied packaging (shop r1: 'the same few primitives in a row'): procedural boxes / bottles in many colours and sizes
                # Infinigen's packaged goods, printed labels with text, art and barcodes: our flat ProductBox / Snack / DrinkCans blocks read
                # as 'untextured toy blocks, a Roblox store' (user 2026-10-17; floor I r27-r28 critics, 3 of 3)
                "groceries": [("inf:FoodBoxFactory", 4), ("inf:FoodBagFactory", 2), ("inf:BottleFactory", 2), ("inf:CanFactory", 1),
                              ("inf:JarFactory", 1)]}
    RACK_MAX_Z = 3.5                                             # rack top shelves are stocked too (the surface placer stops at 1.85 m)

    @property
    def MERCH_HOSTS(self):                                       # kit endcap_open "lib": the open endcaps are stocked from the object library like the gondolas (user 10-25: products from the asset library)
        return ("GondolaFactory", "WallGondolaFactory") + (("PegboardEndcapFactory",) if proc_assets_kit().STYLE.get("endcap_open") == "lib" else ())

    def merch(self, F, levels, mix):
        """Retail facings (user 2026-10-16: random mixes read as a stockroom): one product type per run, identical copies side by side along the shelf edge, front-facing, no jitter; both faces
        of a double gondola. S13 review 10-19: shelves 85-95% occupied, a run of 4-9 of one SKU (ROOM_MERCH_FACING="lo,hi"), tight spacing, and a second row behind the front one when the shelf
        is deep enough (ROOM_MERCH_ROWS, default 2), so the shelf reads full from an angle and not half empty."""
        double = rd._factory(F.name) == "GondolaFactory"
        lo, hi = (int(v) for v in (os.environ.get("ROOM_MERCH_FACING") or "4,9").split(","))
        rows = int(os.environ.get("ROOM_MERCH_ROWS") or 1)                # 2 = a second row behind the first: ~2x stock time (S13 r6: ~1200 s per gondola), so off by default
        self._gap_cache = []
        n = 0
        ends = os.environ.get("ROOM_MERCH_ENDS") == "1"          # ROOM_MERCH_ENDS=1: the short ends of a gondola are stocked too (M r13 CNT-04: 4-5 tiers on the end face almost empty): the long faces stop 0.16 m short of each end, one product facing outwards fills the end
        res = 0.16 if ends else 0.0
        _log(f"merch: {rd._factory(F.name)} ends={'on' if ends else 'off'} (ROOM_MERCH_ENDS={os.environ.get('ROOM_MERCH_ENDS')!r}) levels={len(levels)}")
        for s in levels:
            for side in ((1, -1) if double else (1,)):
                y = s["y0"] + 0.012 + res
                left = 0
                prev_w = []                                      # (y, w, d) of the front row, for the second row
                nf_ = 0
                while y < s["y1"] - 0.04 - res:
                    if left <= 0:
                        cls = self.rng.choices([m for m, _ in mix], [w for _, w in mix])[0]
                        fac = cls(self.rng.randrange(1 << 20))
                        proto, left = None, self.rng.randint(lo, hi)   # identical facings share one mesh (stocking was ~25 min, r1)
                        if proc_assets_kit().VENUE == "pharmacy" and getattr(cls, "__name__", "") == "BottleFactory":
                            left = min(left, 2)                      # pharmacy: a bottle run is 2 at most (S16: four identical pink bottles)
                    left -= 1
                    if proto is not None and not proto.children:
                        o = proto.copy(); o.data = proto.data; bpy.context.scene.collection.objects.link(o)
                    else:
                        o = fac.spawn_asset(n)
                        _shelf_labels(o, self.rng)
                    bpy.context.view_layer.update()
                    if proto is None or o is not proto and not o.get("fit_done"):
                        self._fit_to_level(o, s)                  # a product taller / deeper than the shelf is shrunk to fit, not refused (S13/S16 merch_fill ~0.5)
                    w, d = o.dimensions[1], o.dimensions[0]
                    x = (s["x1"] - d / 2 - 0.02) if side == 1 else (s["x0"] + d / 2 + 0.02)
                    jy_ = self.rng.uniform(-0.14, 0.14) if os.environ.get("ROOM_MERCH_JITTER") == "1" else 0.0      # S37: small yaw / offset jitter so a row is not a ruler line
                    if self.act.try_place(o, F, s, self.rng, None, 0.0, rel_yaw=(0.0 if side == 1 else math.pi) + jy_,
                                          at=(x, y + w / 2), tries=1, jitter=0.004 if jy_ else 0.0):
                        n += 1
                        proto = proto or o
                        prev_w.append((y, w, d, o))
                        nf_ = 0
                    elif proto is not None and o.data is proto.data:
                        bpy.data.objects.remove(o, do_unlink=True)   # a copy: keep the shared mesh
                        if os.environ.get("ROOM_MERCH_TIGHT") == "1":   # S38 r9: a copy refused at pitch w + 6 mm fell through to y += w + 6 mm, so every second facing was lost (occupancy locked at ~50 %): slide on a little and try again
                            left += 1; y += 0.01; continue
                    else:
                        self.act.tidy.delete(o)
                        y += 0.02                                    # a failed spot: slide on a little instead of leaving a long hole
                        if os.environ.get("ROOM_MERCH_TIGHT") == "1":   # S37 r7: a level whose product class never fits (too tall / deep) stayed at 26 %: after 3 refusals of a fresh product the run re-picks its class
                            nf_ += 1
                            if nf_ >= 3:
                                left = 0; nf_ = 0
                        continue
                    y += w + (0.002 if os.environ.get("ROOM_MERCH_TIGHT") == "1" else 0.006)
                self._merch_gaps(F, s, side, mix, [(q[0], q[0] + q[1]) for q in prev_w], res)          # S38 r8: ENDS=1 used to switch the gap fill off, so the long faces kept their holes
                for r_ in range(1, rows):                            # the row(s) behind: the same products one depth further back
                    for yy, ww, dd, src in prev_w:
                        x2 = (src.matrix_world.translation.x) - (side * (dd + 0.015) * r_)
                        if (side == 1 and x2 - dd / 2 < s["x0"]) or (side == -1 and x2 + dd / 2 > s["x1"]):
                            continue
                        o2 = src.copy(); o2.data = src.data; bpy.context.scene.collection.objects.link(o2)
                        bpy.context.view_layer.update()
                        if self.act.try_place(o2, F, s, self.rng, None, 0.0, rel_yaw=0.0 if side == 1 else math.pi, at=(x2, yy + ww / 2), tries=1, jitter=0.0):
                            n += 1
                        else:
                            bpy.data.objects.remove(o2, do_unlink=True)
            if ends:
                for ey, ryaw, sgn in ((s["y1"], math.pi / 2, -1), (s["y0"], -math.pi / 2, 1)):          # a row across the whole depth, fronts towards the aisle end
                    cls = self.rng.choices([m for m, _ in mix], [w for _, w in mix])[0]
                    fac = cls(self.rng.randrange(1 << 20)); proto = None
                    xc = s["x0"] + 0.012; fails_ = 0
                    while xc < s["x1"] - 0.02:
                        if fails_ >= 3 and proto is None:            # S38 r7 CNT-04: a product too deep for the end face left whole tiers bare: re-pick the product after 3 failed spots
                            cls = self.rng.choices([m for m, _ in mix], [w for _, w in mix])[0]; fac = cls(self.rng.randrange(1 << 20)); fails_ = 0
                        if proto is not None and not proto.children:
                            o = proto.copy(); o.data = proto.data; bpy.context.scene.collection.objects.link(o)
                        else:
                            o = fac.spawn_asset(n); _shelf_labels(o, self.rng)
                        bpy.context.view_layer.update()
                        if proto is None or o is not proto and not o.get("fit_done"):
                            self._fit_to_level(o, s)
                        w, d = o.dimensions[1], o.dimensions[0]
                        if self.act.try_place(o, F, s, self.rng, None, 0.0, rel_yaw=ryaw, at=(xc + w / 2, ey + sgn * (d / 2 + 0.02)), tries=1, jitter=0.0):
                            n += 1; proto = proto or o; fails_ = 0
                        elif proto is not None and o.data is proto.data:
                            bpy.data.objects.remove(o, do_unlink=True)
                            if os.environ.get("ROOM_MERCH_TIGHT") == "1":
                                xc += 0.01; continue
                        else:
                            self.act.tidy.delete(o); xc += 0.02; fails_ += 1
                            continue
                        xc += w + 0.006
        for pr in getattr(self, "_gap_cache", []):                # the hidden prototypes of the gap fill
            if pr.name in bpy.data.objects:
                bpy.data.objects.remove(pr, do_unlink=True)
        self._gap_cache = []
        self.stats["placed"]["merch"] = self.stats["placed"].get("merch", 0) + n
        return n

    def _fit_to_level(self, o, s):
        """Scale a fresh product (a single mesh) down so it fits the shelf level: height <= clear - 2.5 cm, depth <= shelf depth - 3 cm (factor >= 0.55); the scale is baked into the mesh (the activity
        placer drops object scale). Copies made afterwards share the baked mesh."""
        try:
            clear = s.get("clear", 0.3) - 0.025; depth = (s["x1"] - s["x0"]) - 0.03
            k = min(1.0, clear / max(o.dimensions[2], 1e-3), depth / max(o.dimensions[0], 1e-3))
            if k < 0.995 and o.type == "MESH" and not o.children:
                k = max(k, 0.55)
                o.scale = (k, k, k)
                bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bpy.context.view_layer.objects.active = o
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
                bpy.context.view_layer.update()
            o["fit_done"] = True
        except Exception:                                          # noqa: BLE001 -- fitting is an extra
            pass

    def _merch_gaps(self, F, s, side, mix, occ, res=0.0):
        """Fill the bare stretches left on one shelf level (S16 r20 CNT-04 'long bare board stretches'): every gap >= 7 cm between placed facings (and the ends) is tried with products from a small
        cache of prototypes spawned once per gondola (copies share the mesh; a prototype too wide for the gap is skipped without any ray test), at most ROOM_MERCH_GAP_TRIES (2) tries per gap and
        ROOM_MERCH_BUDGET_S (20 s) per level. The level's fill ratio goes to stats['merch_fill']. (r6 / r22: spawning a fresh product per try cost ~600-1200 s per gondola.)"""
        import time as _t
        occ = sorted(occ); length = s["y1"] - s["y0"]; gaps, cur = [], s["y0"] + 0.012 + res
        for a, b in occ:
            if a - cur >= 0.07:
                gaps.append((cur, a))
            cur = max(cur, b + 0.006)
        if s["y1"] - 0.04 - res - cur >= 0.07:
            gaps.append((cur, s["y1"] - 0.04 - res))
        tries = int(os.environ.get("ROOM_MERCH_GAP_TRIES") or 2); t_end = _t.time() + float(os.environ.get("ROOM_MERCH_BUDGET_S") or 20.0)
        cache = self.__dict__.setdefault("_gap_cache", [])
        placed = 0.0
        for g0, g1 in gaps:
            y = g0
            for _ in range(tries):
                if g1 - y < 0.06 or _t.time() > t_end:
                    break
                if len(cache) < int(os.environ.get("ROOM_MERCH_GAP_CACHE") or 8):
                    cls = self.rng.choices([m for m, _ in mix], [w for _, w in mix])[0]
                    pr = cls(self.rng.randrange(1 << 20)).spawn_asset(0)
                    _shelf_labels(pr, self.rng)
                    bpy.context.view_layer.update()
                    self._fit_to_level(pr, s)
                    pr.hide_render = True; pr.hide_viewport = True; cache.append(pr)
                fits = [q for q in cache if q.dimensions[1] <= g1 - y - 0.004]
                if not fits:
                    break
                pr = self.rng.choice(fits); w, d = pr.dimensions[1], pr.dimensions[0]
                o = pr.copy(); o.data = pr.data; o.hide_render = False; o.hide_viewport = False; bpy.context.scene.collection.objects.link(o)
                x = (s["x1"] - d / 2 - 0.02) if side == 1 else (s["x0"] + d / 2 + 0.02)
                if self.act.try_place(o, F, s, self.rng, None, 0.0, rel_yaw=0.0 if side == 1 else math.pi, at=(x, y + w / 2), tries=1, jitter=0.0):
                    placed += w + 0.006; y += w + 0.006
                    self.stats["placed"]["merch"] = self.stats["placed"].get("merch", 0) + 1
                else:
                    bpy.data.objects.remove(o, do_unlink=True)
                    if os.environ.get("ROOM_MERCH_TIGHT") == "1":
                        y += 0.01
        used = sum(b - a for a, b in occ) + placed
        mf_ = self.stats.setdefault("merch_fill", []); mf_.append(round(min(1.0, used / max(length - 2 * res, 1e-3)), 2))
        self.stats["merch_fill_min"] = min(mf_); self.stats["merch_fill_mean"] = round(sum(mf_) / len(mf_), 2); self.stats["merch_fill_lt85"] = sum(1 for v_ in mf_ if v_ < 0.85)       # per-level occupancy of the front row (S38 r8: verify without a VLM)

    CHAIR_ISSUE_GUARD = os.environ.get("ROOM_CHAIR_WALL_GUARD", "1") != "0"

    def fill(self, it, cls):
        mix = [(_cls(src), w) for src, w in self.FILL_MIX.get(it["category"], [])] or [(cls, 1)]
        if it["category"] == "cardboard_box" and (LAB or os.environ.get("ROOM_LAB_CEILING")):      # a lab's store: no grocery cartons (N2 r7 DOM-01: jars / cans / food boxes on lab shelves)
            mix = [m for m in mix if getattr(m[0], "__name__", "") != "FoodBoxFactory"] or mix
        if it["category"] == "boutique_stock":                                    # S15: folded garments, shoe boxes and bags on the wall gondolas
            mix = [(_cls("proc:FoldedGarmentFactory"), 6), (_cls("proc:ShoeBoxFactory"), 3), (_cls("proc:HandbagFactory"), 1)]
        if proc_assets_kit().VENUE == "pharmacy" and it["category"] == "groceries":       # many small uniform packs (pharmacy ref: 4-8 cm boxes), a few bottles
            from room_planner import pharmacy_boxes as _pb
            mix = [(_cls("inf:FoodBoxFactory" if _pb.enabled() and _pb.label_files() else "proc:SmallPackFactory"), 8), (_cls("inf:BottleFactory"), 1.5)]      # no inf:FoodBox: it prints cereal ('Corn Flakes') boxes (S16 r27 DOM-01: cereal in a pharmacy)
        if it["category"] == "groceries" and proc_assets_kit().STYLE.get("merch_mix"):      # kit merch_mix [[src, weight], ...]: S37 r4, e.g. + inf:CupFactory (cup noodles) beside bags / cans / bottles
            mix = [(c_, float(w_)) for c_, w_ in ((_safe_cls(src_), w0_) for src_, w0_ in proc_assets_kit().STYLE["merch_mix"]) if c_ is not None] or mix
        if getattr(self, "_mix_override", None):                                   # ROOM_STOCK_DAILY: the daily-needs wall units
            mix = self._mix_override
        if it["category"] == "groceries":                                          # stocked once: _fill_gondolas stocks planned units first, the plan's own fill entry came again 10-20 min later (S16 r29)
            done = self.__dict__.setdefault("_groceries_filled", set())
            if it["on"] in done:
                return
            done.add(it["on"])
        if it["category"] == "backbar_stock" and proc_assets_kit().STYLE.get("backbar_mix"):      # kit backbar_mix [[src, weight], ...]: S31 r14 'scattered cups with long empty spans' -> bottles and jars
            mix = [(c_, float(w_)) for c_, w_ in ((_safe_cls(src_), w0_) for src_, w0_ in proc_assets_kit().STYLE["backbar_mix"]) if c_ is not None] or mix
        n0 = sum(self.stats["placed"].values())
        for F, _ in getattr(self, "copies", {}).get(it["on"], [self.ids[it["on"]]]):
            bpy.context.view_layer.update()
            levels = self.act.supports(F, bpy.context.evaluated_depsgraph_get(), top_only=False)
            levels = [s for s in levels if (F.matrix_world @ Vector((0, 0, s["z"]))).z < self.RACK_MAX_Z and s["clear"] > 0.12]
            if rd._factory(F.name) in ("GondolaFactory", "WallGondolaFactory"):   # shelves only, not the open top: stock stood on the
                hi = max((s_["z"] for s_ in levels), default=0)                    # gondola tops and read as 'floating crates' (shop
                levels = [s_ for s_ in levels if s_["z"] < hi - 0.05 or s_["clear"] < 1.0]   # r11, 3 of 3)
            self.act.mark_occupied(F, levels, self.act.corners_of(rd._tops()))
            if rd._factory(F.name) in self.MERCH_HOSTS or it["category"] == "groceries":   # any shelf of goods is faced, not scattered
                                                                                          # (shop r7: pharmacy back shelves 'a third full')
                self.merch(F, levels, mix)
                continue
            for s in levels:
                misses, cap = 0, min(self.rng.choice(tuple(int(v) for v in (os.environ.get("ROOM_FILL_CAPS") or "6,12,24,24").split(","))), int(os.environ.get("ROOM_FILL_MAX", "24")))  # uneven stock, mostly full (r1: bare; r9: 'one carton per level')   # env ROOM_FILL_MAX: items per shelf level (floors: a stockroom rack took 15 min at 75 items, floor M r1)
                if os.environ.get("ROOM_RACK_FULL") == "1" and rd._factory(F.name) == "StorageRackFactory":    # O3 r3 / O4 r4 F5: sparse racks -> every shelf full: more boxes + bins, a few mop buckets / tools
                    cap = int(os.environ.get("ROOM_RACK_CAP") or 16)      # O4 r6: cap 26 / 16 misses placed 302 items in 3,100 s of realize time (load ~90); 16 / 9 keeps racks full for about half
                    if LAB or os.environ.get("ROOM_LAB_CEILING") or proc_assets_kit().VENUE not in ("grocery", "convenience", "cafe", "pharmacy", "boutique", "bakery", "market"):      # N2 r23 DOM-01: lab / office / clinic racks hold cartons, bins and binders, not cereal
                        mix = [(c_, w_) for c_, w_ in ((_safe_cls("proc:CardboardBoxFactory"), 6), (_safe_cls("proc:PlasticBinFactory"), 4), (_safe_cls("proc:MopBucketFactory"), 0.25), (_safe_cls(catalog.LIVED_IN["book_stack"]["src"]), 1.0)) if c_ is not None]
                    else:
                        mix = [(_cls("proc:CardboardBoxFactory"), 5), (_cls("proc:PlasticBinFactory"), 4), (_cls("proc:MopBucketFactory"), 0.3), (_cls("inf:BottleFactory"), 1.5), (_cls("inf:FoodBoxFactory"), 2.5), (_cls("inf:JarFactory"), 1)]
                if it["category"] == "book_stack":               # a bookcase is full, not 6 / 12 books (O2 CNT-04)
                    cap = int(os.environ.get("ROOM_BOOK_CAP") or 12)
                while misses < (int(os.environ.get("ROOM_RACK_MISSES") or 9) if (os.environ.get("ROOM_RACK_FULL") == "1" and rd._factory(F.name) == "StorageRackFactory") else 6) and len(s["placed"]) < cap:
                    c = self.rng.choices([m for m, _ in mix], [w for _, w in mix])[0]
                    misses = 0 if self._item(c, F, s, "placed") is not None else misses + 1
        _log(f"fill {it['on']} ({it['category']}): {sum(self.stats['placed'].values()) - n0} items on "
             f"{len(getattr(self, 'copies', {}).get(it['on'], []))} copies")

    def lived_in(self, it):
        if it.get("category") not in catalog.LIVED_IN:                 # H5 r1: the planner named "laptop", which is not in the vocabulary -> KeyError killed a 26-room activity pass
            self.stats.setdefault("lived_in_unknown", []).append(it.get("category")); return
        if it["category"] == "cardboard_box" and it["on"] == "floor" and self.doc.get("type") == "warehouse" and self.doc.get("area_m2", 0) >= 120:
            pal = next((k for k, (o_, _) in self.ids.items() if rd._factory(o_.name) == "PalletFactory"), None)
            if pal is None:                                      # a hall's loose cartons go on a pallet, never free in an aisle (floor J
                return                                           # r13: 'debris, tipped boxes in the aisles', 3 of 3)
            it = {**it, "on": pal}
        if it["category"] in ("pen_cup", "phone", "clipboard", "speakerphone"):   # one of these a desk: three pen cups with fanned
            self.one_per = getattr(self, "one_per", set())                       # pens read as 'toy cones, party hats' (A2 r11, 2/3)
            if (it["on"], it["category"]) in self.one_per:
                return
            self.one_per.add((it["on"], it["category"]))
            it = {**it, "count": 1}
        if it["category"] in ("bottle", "wine_bottle") and it["on"] in self.ids and \
                rd._factory(self.ids[it["on"]][0].name) == "WorkbenchFactory":
            return                                               # 'wine bottles on a packing bench read as a kitchen counter' (J r15, 3/3)
        if it["on"] in self.ids and rd._factory(self.ids[it["on"]][0].name) == "PalletRackFactory":
            return                                               # loaded with its own pallets and cartons
        if it["category"] == "monitor":                          # one screen per desk (floor A2 r8: three on a private office desk, two
            self.monitors = getattr(self, "monitors", {})       # facing away from the chair, layout 6, 3 of 3)
            h_ = self.ids.get(it["on"])
            if self.monitors.get(it["on"], 0) >= 1 or (h_ and rd._factory(h_[0].name) in ("OfficeDeskFactory", "ClinicDeskFactory")):
                return                                           # those desks carry their own screens: a second one stood inside the first
                # at an angle (floor A2 r9: 'two monitors collide on the desk', 3 of 3)
            self.monitors[it["on"]] = 1
            it = {**it, "count": 1}
        if it["on"] == "floor" and "floor" not in catalog.LIVED_IN[it["category"]].get("on", ["floor"]):
            return                                               # the vocabulary's hosts bind (floor I r14: baskets on the floor of the
                                                                 # queue path, 'a dropped delivery', 3 of 3)
        if it["category"] == "draped_clothes":                   # the catalog 'on' list is not checked for plan hosts: a shirt on an armchair fell to the floor (P2 r12 LAY-02)
            h_ = self.ids.get(it["on"])
            if h_ is None or not any(k in rd._factory(h_[0].name) for k in ("Bed", "Sofa")):
                return
        cls = _cls(catalog.LIVED_IN[it["category"]]["src"])
        if it["category"] in ("small_plant", "desk_plant") and proc_assets_kit().STYLE.get("infinigen_plants"):    # every plant from Infinigen (S10: the ABO planter plants read stiff)
            cls = _cls("proc:TablePlantFactory")
        pose = it.get("pose", "placed")
        for _ in range(it.get("count", 1)):
            host = self.ids.get(it["on"])
            if host is None and it["on"] != "floor":             # its host was dropped: a lamp does not belong on the floor
                self.stats["no_host"] = self.stats.get("no_host", 0) + 1
                continue
            if it["category"] == "autoclave" and host is not None and rd._factory(host[0].name) == "MedicalCabinetFactory":
                # on the worktop at the far end from the sink: the top finder sees only the upper cabinets' top (floor E3 r7: 'no fit')
                R = host[0]
                o = cls(self.rng.randrange(1 << 24)).spawn_asset(self.stats["furniture_added"])
                k_ = self.autoclaves = getattr(self, "autoclaves", 0) + 1   # a second unit one slot along (floor E3 r12: 'a small round
                # object, no autoclave', steri 4/7/6/5/5, 3 of 3)
                if k_ > 1 and R.dimensions[1] < 2.9:             # a 2.4 m run: the second slot is the sink's
                    bpy.data.objects.remove(o, do_unlink=True)
                    continue
                o.matrix_world = R.matrix_world @ Matrix.Translation((0.1, R.dimensions[1] / 2 - 0.65 - 0.62 * (k_ - 1), 0.942))   # + its bath
                print("[lived] autoclave on MedicalCabinetFactory (worktop slot): ok", flush=True)
                continue
            if host is None:
                o = self.spawn(cls)
                if o is None:
                    return
                w, d = o.dimensions[0], o.dimensions[1]
                spots = (self._near_spots(it["near"], w, d) if it.get("near") in self.ids else []) + self.spots({"relation": "corner"}, w, d)
                _log(f"{it['category']} on floor: {len(spots)} spots, {len(o.data.vertices) if o.type == 'MESH' else 0} verts")
                if any(fr._place(o, x, y, yaw, self.room, self.obstacles, fr.INF_FRONT) for x, y, yaw in spots):
                    if pose in ("tossed", "leaning", "lying"):
                        self.toss.append((o, None, "tossed", False))
                else:
                    self.act.tidy.delete(o); self.stats["no_room"] += 1
                continue
            F = host[0]
            from room_planner import proc_assets as _pa2
            if "Bed" in F.name and _pa2.STYLE.get("bed_style") == "soft_white" and it["category"] in ("cushion", "throw_blanket"):
                continue                                         # P2b: the soft bed carries its own petrol throw + cushions; the lived-in ABO pillow was the coral one
            if rd._factory(F.name) in SOFT:
                cat = it["category"]
                if cat == "throw_blanket" and "Bed" not in F.name:          # ponytail: rigid 2 m sheet on a sofa = a slab; cloth sim later
                    cls = _cls(catalog.LIVED_IN["cushion"]["src"])
                self._drop_on(cls, host, "leaning" if pose == "leaning" else "tossed", cat)
                continue
            shelf = rd._factory(F.name) in SHELVES
            bpy.context.view_layer.update()
            levels = self.act.supports(F, bpy.context.evaluated_depsgraph_get(), top_only=not shelf)
            levels = [s for s in levels if (F.matrix_world @ Vector((0, 0, s["z"]))).z < self.act.MAX_Z]
            if not levels:
                self.stats["no_room"] += 1
                print(f"[lived] {it['category']} on {rd._factory(F.name)}: no support level", flush=True)
                continue
            self.act.mark_occupied(F, levels, self.act.corners_of(rd._tops()))
            if it.get("fill"):                                   # stock every level of every copy: a working rack is full
                self.fill(it, cls)
                break
            s = self.rng.choice(levels) if shelf else max(levels, key=lambda s: len(s["cells"]))   # seat, bed top, table top
            o = self._item(cls, F, s, pose)
            print(f"[lived] {it['category']} on {rd._factory(F.name)} ({pose}): {'ok' if o else 'no fit'}", flush=True)
            if o is not None and pose in ("tossed", "leaning") and not shelf:
                self.toss.append((o, host, pose, False))

    def place_all(self, items) -> list:
        """Furniture items in plan order, a second round for those whose target came later. Returns [(item, reason)] not placed."""
        items = [it for it in items if it.get("id") not in self.ids]
        items = [({**it, "avoid_windows": True} if (it["category"] in ("home_kitchen_run", "big_fridge", "medical_cabinet", "pantry_run", "pantry_run", "oven_tower", "locker", "bedroom_media", "media_wall", "lab_chamber", "lab_cabinet", "instrument_rack", "gondola", "wall_gondola", "pharmacy_drawer_wall", "pegboard_endcap", "cooler_wall", "bookshelf", "bookcase", "office_bookcase", "storage_rack", "supply_shelf", "stock_shelf", "vanity") or (it["category"] == "bed" and self.doc.get("area_m2", 0) >= 20)) else it) for it in items]   # + tall retail units off the glazing (S16 r20 LAY-01: a shelving unit across the front window)
        # wall-cabinet runs on a solid wall first: a sink run with uppers built across a window 'is not buildable' (floor F3 r17, 2 of 3)
        if self.doc.get("type") == "open-office" and getattr(self, "pods_placed", 0):
            # the pod grid is the open plan's desking: loose desks went in the aisles at odd angles with chairs round them (floor C r9:
            # 'furniture dumped in storage', layout 5, 3 of 3)
            items = [it for it in items if it["category"] != "office_desk"]
        from room_planner import proc_assets as _pa1
        if self.doc.get("type") == "office" and getattr(_pa1, "FLOOR_VENUES", ()):   # the revision re-added the floor tree the plan
            items = [it for it in items if it["category"] != "floor_plant"]          # cleanup dropped ('a potted tree in the middle', F3 r16)
        if self.doc.get("type") == "exam-room":               # no tall filing in a treatment room: it jammed into the sink run (F3 r18)
            items = [it for it in items if it["category"] != "filing_cabinet"]
        if self.doc.get("type") == "clinic-reception":         # the revision re-added them (D3 r13: 'files_1 filing_cabinet beside')
            items = [it for it in items if it["category"] != "filing_cabinet"]
            cap = 2 if self.doc.get("area_m2", 0) >= 35 else 3  # wall benches, all paths (plan, revision, fill): with the island a lobby
            have_ = sum(1 for o_, _ in self.ids.values() if rd._factory(o_.name) == "WaitingBenchFactory")   # had ~8 rows, 'a showroom' (E3 r16)
            kept = []
            for it in items:
                if it["category"] == "waiting_bench":
                    if have_ >= cap:
                        continue
                    have_ += it.get("count", 1)
                kept.append(it)
            items = kept
        if self.doc.get("type") == "office":                   # one filing cabinet in a private office (floor C r9: 2-4 crowd the door
            n_fc = sum(1 for o_, _ in self.ids.values() if rd._factory(o_.name) == "FilingCabinetFactory")   # wall, 3 of 3)
            fc = [it for it in items if it["category"] == "filing_cabinet"]
            items = [it for it in items if it["category"] != "filing_cabinet"] + ([{**fc[0], "count": 1}] if fc and not n_fc else [])
        items = [({**it, "avoid_windows": True} if it["category"] in ("filing_cabinet", "office_bookcase") else it) for it in items]
        items = [({**it, "count": max(3, it.get("count", 1))} if it["category"] == "break_chair" and it.get("relation") == "around" else it)
                 for it in items]   # a staff table seats three or more: the revision's 'chair1 around' gave it one (floor G r30: comp 6)
        # tall storage off the glazing (floor J r19: 'a filing cabinet standing in front of the window', layout 6, 3 of 3)
        if RELAX_ZONES:                                          # home recipes: the bed goes first, before the desk / nightstands take the one wall it fits on (P2 r9 bedroom_0/2)
            items = sorted(items, key=lambda it: 0 if it["category"] in ("bed", "single_bed") else 1)
        self.pending_ids = {it["id"] for it in items}
        self.plan_items = getattr(self, "plan_items", []) + list(items)   # seats check whether their table was a planned item
        failed = []
        for _ in range(2):
            later = []
            for it in items:
                r = self._safe_furniture(it)
                if r is False and it.get("relation") == "beside" and it["category"] in ("pegboard_endcap", "basket_stack", "bread_display", "cooler_wall", "category_sign"):
                    r = self._safe_furniture({**it, "relation": "against_wall"})   # a retail end cap / stack with no free spot beside its target goes on a wall (S13 r4: one end cap refused)
                if r is False and it.get("relation") == "corner":   # any wall when no corner is free (floor J r17: the washroom's WC
                    r = self._safe_furniture({**it, "relation": "against_wall"})   # dropped at 'corner', a WC-less washroom, function 4, 3 of 3)
                if r is None:
                    later.append(it)
                    continue
                self.pending_ids.discard(it["id"])
                if not r:
                    failed.append((it, "no free spot for its relation (footprint off the floor or touching other furniture)"))
            items = later
            self.pending_ids = {it["id"] for it in items}
        failed += [(it, f"its target {it.get('target')} was never placed") for it in items]
        return failed

    def fill_empty(self, plan):
        """Cafes only: no large empty floor (user 2026-10-16: a busy cafe's usable floor is all seating, circulation, queue or
        counter). The largest empty region >= 3 m2 gets a cafe table with 2 (4 if >= 6 m2) chairs around it, until none is left;
        door zones and the counter front are already obstacles. A spot that fails is blocked so the next try moves on."""
        if ROOFTOP or WINEPUB or self.mode:                           # the layout already ran first in run(); the standard cafe fill must not add to it
            return 0
        from room_planner import proc_assets
        if proc_assets.VENUE in ("clinic-reception", "exam-room", "dental-room", "physio-room") or self.doc.get("type") in ("restroom", "hallway", "closet") or \
                getattr(self, "staff_hooks", False) or \
                (self.doc.get("type") == "office" and getattr(proc_assets, "FLOOR_VENUES", ())) or \
                str(self.doc.get("id", "")).startswith("utility"):   # a floor's stockroom, whatever venue it took
            self._clinic_walls()
        if proc_assets.VENUE in ("grocery", "convenience", "pharmacy"):
            return self._fill_gondolas(plan)
        if proc_assets.VENUE == "boutique":
            return self._fill_boutique(plan)
        if proc_assets.VENUE == "warehouse":                     # racks until the floor is aisles (warehouse r4: 'a hangar with a few shelves')
            for rid, (o_, _) in list(self.ids.items()):          # planned wall racks are stocked too (floor I r7: two bare racks -- the plan
                if rd._factory(o_.name) in ("StorageRackFactory", "SupplyShelfFactory") and ":" not in rid and not rid.startswith("aisle_") and not plan.get("fixed"):   # gave no lived_in; a FIXED program stocks its own racks (G r50: grocery packs + cartons over the kit's bins / towels)
                    st_ = "cafe_stock" if "cafe" in getattr(proc_assets, "FLOOR_VENUES", ()) else "cardboard_box"   # a café's back
                    # stock: this carton fill ran first and left the café items no shelf -- 'toy blocks, nothing says café' (G r34)
                    self.fill({"on": rid, "category": st_}, _cls(catalog.LIVED_IN[st_]["src"]))
            n0 = len(self.ids)
            if sum(f.get("count", 1) for f in plan.get("furniture", []) if f["category"] == "workbench") >= 2 and \
                    self.doc.get("area_m2", 0) < 120:            # a fulfilment hall has benches AND aisles (floor J r4: 254 m2, 'packing
                                                                 # benches' -> no aisles, a bare hangar floor)   # a packing room: benches,
                self._fill_items(plan, ("pallet", "utility_cart"), 3.5, limit=2)  # not a hall of aisles (wh r7); the plan owns the benches
                return self._working_floor(boxes=False)   # (r13: a classroom grid; r16: 'loose cartons choke the floor', layout 6)
            if self.doc.get("area_m2", 0) >= 120 and self.walls:  # a hall: heavy pallet racking along its longest wall first (floor J
                lw = max(self.walls, key=lambda k: self.walls[k][3])   # r13-r15: '2 m shelving under a 5 m roof, a big stockroom', 3/3)
                n_b = max(2, int((self.walls[lw][3] - 2.0) / 2.77))
                self.furniture({"id": "pallet_racks", "category": "pallet_rack", "relation": "row", "wall": lw, "count": n_b})
            if self.doc.get("area_m2", 0) >= 20:                 # a back stockroom's racks stay on its walls (floor G r11: an aisle rack
                self._rack_aisles()                              # facing the wall racks left 'a body-width aisle', 3 of 3)
            for rid in [k for k in list(self.ids)[n0:] if k.startswith("aisle_")]:
                self.fill({"on": rid, "category": "cardboard_box"}, _cls(catalog.LIVED_IN["cardboard_box"]["src"]))
            if self.doc.get("area_m2", 0) >= 20:                 # not in a back stockroom (floor H r11: pallets in the door path)
                self._working_floor()
            return
        if proc_assets.VENUE == "clinic-reception":              # clinic r8: 'one bench in a large empty floor, a lobby with a counter'
            for o, front in [v for v in self.ids.values() if rd._factory(v[0].name) == "ReceptionDeskFactory"]:
                c_, f_, w_, d_ = _frame(o, front)                 # the counter approach stays clear (clinic r13: the extra bench was
                q0, q1 = c_ + f_ * (d_ / 2), c_ + f_ * (d_ / 2 + 1.8)   # parked against its front, backs to the staff)
                sv = _left(f_) * (w_ / 2 + 0.3)
                xs = [q0.x + sv.x, q0.x - sv.x, q1.x + sv.x, q1.x - sv.x]; ys = [q0.y + sv.y, q0.y - sv.y, q1.y + sv.y, q1.y - sv.y]
                self.obstacles.append((min(xs), max(xs), min(ys), max(ys), 0, 0))
            # one extra row only (clinic r10/r12: four-five rows read as a lecture hall)
            desk = next((v[0].location for v in self.ids.values() if rd._factory(v[0].name) == "ReceptionDeskFactory"), None)
            if self.doc.get("area_m2", 0) >= 35:                # a large lobby: benches line the walls, a side table in the middle
                n0 = len(self.ids)                               # (floor D3 r5: 'a large, nearly empty box', 3 of 3)
                # a seating island: a clinic low table with a bench row facing it from each side (floor D3/F3 r8: 'an empty hall
                # with a lone residential coffee table', 6 of 6 calls)
                self._waiting_island(plan)
                if self.doc.get("area_m2", 0) >= 45:            # a second island in the next empty region: a 52 m2 lobby with one
                    self._waiting_island(plan)                   # island and two wall rows was 'an empty hall', 30 m2 bare (E3 r19, 3 of 3)
                for F in (proc_assets.WaterCoolerFactory, proc_assets.OliveTreeFactory):   # a water cooler and a plant on the walls (floor D3
                    o = F(self.rng.randrange(1 << 24)).spawn_asset(self.stats["furniture_added"])   # r11: 'no plants, no water cooler', 3/3)
                    bpy.context.view_layer.update()
                    sp = self.spots({"relation": "corner" if F is proc_assets.OliveTreeFactory else "against_wall"}, o.dimensions[1], o.dimensions[0])
                    if any(fr._place(o, x, y, yaw, self.room, self.obstacles, fr.INF_FRONT) for x, y, yaw in sp):
                        self.stats["furniture_added"] += 1
                    else:
                        bpy.data.objects.remove(o, do_unlink=True)
                return
            if sum(rd._factory(v[0].name) == "WaitingBenchFactory" for v in self.ids.values()) >= 3:   # three rows already (r27)
                return
            return self._fill_items(plan, ("waiting_bench",), 3.0, limit=1,      # the extra row faces the counter (clinic r19:
                                    face=(desk.x, desk.y) if desk else None)     # 'backs to the desk, facing the window', 2 of 3)
        if proc_assets.VENUE == "physio-room":                   # clinic r3: 'a large, almost empty white room'
            for o, front in [v for v in self.ids.values() if rd._factory(v[0].name) == "ParallelBarsFactory"]:
                f = fr.footprint(o)                               # a clear walking lane: the bars plus 1 m at both ends (clinic r14:
                self.obstacles.append((f[0] - 1.0, f[1] + 1.0, f[2] - 1.0, f[3] + 1.0, 0, 0))   # 'bikes stand in the gait lane')
            return self._fill_items(plan, ("exercise_set", "exercise_bike", "exercise_set"), 3.0)   # beds come from the plan only (r13: end-to-end beds)
        if proc_assets.VENUE == "break-room":                    # pantry r8: a big empty floor read as an unfurnished room
            if self.doc.get("area_m2", 0) >= 18:                 # a second element on another wall: a drinks cooler (pantry r18: 'half the
                o = proc_assets.DisplayCoolerFactory(self.rng.randrange(1 << 24)).spawn_asset(self.stats["furniture_added"])   # room is dead')
                bpy.context.view_layer.update()
                spots = self.spots({"relation": "against_wall"}, o.dimensions[1], o.dimensions[0])
                if any(fr._place(o, x, y, yaw, self.room, self.obstacles, fr.INF_FRONT) for x, y, yaw in spots):
                    self.stats["furniture_added"] += 1
                else:
                    bpy.data.objects.remove(o, do_unlink=True)
            if self.doc.get("area_m2", 0) >= 18:                 # a recycling station on a free wall and a board above it (pantry r21)
                o = proc_assets.RecycleBinsFactory(self.rng.randrange(1 << 24)).spawn_asset(self.stats["furniture_added"])
                bpy.context.view_layer.update()
                spots = self.spots({"relation": "against_wall"}, o.dimensions[1], o.dimensions[0])
                self.rng.shuffle(spots)
                if any(fr._place(o, x, y, yaw, self.room, self.obstacles, fr.INF_FRONT) for x, y, yaw in spots):
                    self.stats["furniture_added"] += 1
                else:
                    bpy.data.objects.remove(o, do_unlink=True)
                self._wall_mount("whiteboard", self.WALL_MOUNTED["whiteboard"])
            if not proc_assets_kit().STYLE.get("no_break_tables"):                  # a kit that forbids tables (N2 lobby) gets none from the empty-region fill either
                self._fill_tables(plan, "break_table", "break_chair", 4.0)
            if proc_assets_kit().STYLE.get("no_break_tables"):
                return 0
            return self._fill_tables(plan, "cafe_table", "cafe_chair", 2.5)   # smaller gaps get a 2-4 seat table (pantry r22: a 4.6 m2
                                                                               # region left empty -- the 1.6 m table and its chairs did not fit)
        if proc_assets.VENUE == "open-office":
            return self._fill_pods(plan)
        if proc_assets.VENUE != "cafe":
            return
        self._counter_lanes()
        ox, oy = self.doc["_origin"]
        added = 0
        dens = (proc_assets.STYLE.get("density") or {}).get("seats_per_10m2")
        x0_, x1_, y0_, y1_ = self.room.box
        target = dens * (x1_ - x0_) * (y1_ - y0_) / 10.0 if dens else None   # the kit's seat density (non-home 20: 'too sparse')
        if target and self.doc.get("area_m2", 0) > 60:           # a floor's café hall: the user's 'seating, circulation, queue or counter' --
            target *= 0.65 if self.doc.get("area_m2", 0) > 120 else 0.5   # 0.75: 'over-packed, no lane to the
            # counter' (floor H r41, layout 6-7, 3 of 3)   # a 164 m2 hall at 0.5 kept every seat in one block, 'half the
            # hall empty' (floor H r30-r33, 3 of 3 each); the fill takes the largest empty region first                                        # the full kit density left one-chair aisles (floors G/H r7-r10, layout 5-6, 6 of 6);
                                                                 # 0.7 still 'a tight grid, chairs touching' (floor G r11, layout 5, 3 of 3)
        def seats_now():                                         # on this room's floor: the box of an L-shaped hall takes in the
            return sum(1 for o in bpy.data.objects if o.type == "MESH" and any(k_ in o.name for k_ in ("Chair", "Stool", "chair"))   # staff room
                       and x0_ <= o.location.x <= x1_ and y0_ <= o.location.y <= y1_ and self.room.on_floor(o.location.x, o.location.y))
        _log(f"fill_empty: target {target} seats, {seats_now()} now")
        for k in range(16):
            if target is not None and seats_now() >= target:
                break
            regs = [r for r in self.report(plan, [])["empty_floor"] if r["area_m2"] >= (2.0 if target else 3.0)
                    and min(r["x_range"][1] - r["x_range"][0], r["y_range"][1] - r["y_range"][0]) >= 2.2]   # room for chairs round it:
            # a 17.6 m2 band by the windows took a table ten times and never a chair (floor H r36)
            if not regs:
                break
            r = regs[0]
            cx, cy = ox + sum(r["x_range"]) / 2, oy + sum(r["y_range"]) / 2
            tid = f"fill_t{k}"
            o, front = self._make("cafe_table")
            yaw = self.rng.uniform(-0.17, 0.17)                   # a small turn: a grid of square tables read as a conference room (r2), but a
            # table at 45 deg has an axis-aligned obstacle box 1.4x wide that covered every chair spot -- 'table placed, no chair
            # fitted', +0 groups, half the hall empty (floor H r35-r38, debug: every spot hit the table's own box)
            cand = [(cx + dx, cy + dy) for dx in (0, 0.4, -0.4, 0.8, -0.8) for dy in (0, 0.4, -0.4, 0.8, -0.8)]   # cafe r3: +0 groups
            gx0, gx1 = ox + r["x_range"][0] + 0.6, ox + r["x_range"][1] - 0.6
            gy0, gy1 = oy + r["y_range"][0] + 0.6, oy + r["y_range"][1] - 0.6
            cand += sorted(((gx0 + 0.5 * i, gy0 + 0.5 * j) for i in range(max(0, int((gx1 - gx0) / 0.5)) + 1)
                            for j in range(max(0, int((gy1 - gy0) / 0.5)) + 1)), key=lambda p_: (p_[0] - cx) ** 2 + (p_[1] - cy) ** 2)[:80]
            # + a grid over the region: a large empty band wrapped round the seating has its box centre ON the tables, so every try
            # failed (floor H r30-r35: 'target 63 seats, 23 now', +0 groups, 'half the hall empty')
            if o is None or not any(fr._place(o, x, y, yaw, self.room, self.obstacles, front) for x, y in cand):
                _log(f"fill_empty: table at ({cx:.1f},{cy:.1f}) region {r['area_m2']} m2 found no spot")
                if o is not None:
                    bpy.data.objects.remove(o, do_unlink=True)
                self.obstacles.append((cx - 0.4, cx + 0.4, cy - 0.4, cy + 0.4, 0, 0))   # move on
                continue
            self.ids[tid] = (o, front); self.stats["furniture_added"] += 1
            seats = self.rng.choice((2, 2, 3, 4)) if r["area_m2"] >= 6.0 else 2
            self.pending_ids = set()
            if not self.furniture({"id": tid + "c", "category": "cafe_chair", "relation": "around", "target": tid, "count": seats}):
                # a table no chair fits round is an orphan in the walkway (floor H r21-r22: 'a lone table by the entrance', 3 of 3)
                _log(f"fill_empty: table at ({cx:.1f},{cy:.1f}) placed, no chair fitted")
                del self.ids[tid]; self.stats["furniture_added"] -= 1; getattr(self, "copies", {}).pop(tid, None)
                f_ = fr.footprint(o); bpy.data.objects.remove(o, do_unlink=True)
                self.obstacles.append((f_[0] - 0.8, f_[1] + 0.8, f_[2] - 0.8, f_[3] + 0.8, 0, 0))   # block its surroundings: move on
                continue
            if self.rng.random() < 0.5:
                self.lived_in({"category": "mug", "on": tid})
            added += 1
        self.stats["filled_groups"] = self.stats.get("filled_groups", 0) + added
        _log(f"fill_empty: +{added} table groups")
        self._plants_to_kit()

    def _plants_to_kit(self):
        """Styled cafés: plants up to the kit's count (style eval 2026-10-16: kits ask 9-14, renders had 1-3) -- on the floor at corners,
        windows and walls, and when the kit has hanging_plants half of them hung from the ceiling 0.35 m off the walls, clear of doors."""
        from room_planner import proc_assets as pa
        want = (pa.STYLE.get("density") or {}).get("plants")
        if not want:
            return
        x0, x1, y0, y1 = self.room.box
        def have():
            return sum(1 for o in bpy.data.objects if o.type == "MESH" and any(k in o.name for k in ("OliveTree", "Plant"))
                       and x0 <= o.location.x <= x1 and y0 <= o.location.y <= y1)
        hang = "hanging_plants" in (pa.STYLE.get("decor") or []) and self.room.wall is not None and os.environ.get("ROOM_HANGING_PLANTS") == "1"   # off by default: the procedural pothos is not an Infinigen plant (user rule; H r72 AST-01 'flat circular leaves on rigid stems')
        n0 = have()
        for k in range(12):
            if have() >= (want // 2 if hang else want):
                break
            self.pending_ids = set()
            self.furniture({"id": f"kit_p{k}", "category": "floor_plant", "relation": ("corner", "near_window", "against_wall")[k % 3]})
        hung = 0
        if hang:
            zc = max((self.room.wall.matrix_world @ Vector(c)).z for c in self.room.wall.bound_box)
            doors = [(d["wall"], d["at_m"]) for d in self.doc.get("doors", [])]
            spots = [(a + t_ * (L * f) + n * 0.35) for wid, (a, t_, n, L) in self.walls.items() for f in (0.2, 0.4, 0.6, 0.8)
                     if all(w_ != wid or abs(L * f - at) > 1.3 for w_, at in doors)]
            self.rng.shuffle(spots)
            for p in spots[:max(0, want - have())]:
                o = pa.HangingPlantFactory(self.rng.randrange(1 << 24), drop=self.rng.uniform(0.4, 0.6)).spawn_asset(hung)
                o.location = (p.x, p.y, zc - 0.02)
                hung += 1
        self.stats["kit_plants"] = have() - n0
        _log(f"plants to kit: {n0} -> {have()} (want {want}, hung {hung})")

    def _main_aisle(self, width=1.5):
        """A clear strip from the door straight across the room (user 2026-10-16: an office needs a circulation spine)."""
        for d in self.doc.get("doors", []):
            if d["wall"] not in self.walls:
                continue
            a, t_, n, length = self.walls[d["wall"]]
            p = a + t_ * d["at_m"]
            far = p + n * 20
            far.x = min(max(far.x, self.room.box[0]), self.room.box[1]); far.y = min(max(far.y, self.room.box[2]), self.room.box[3])
            w = t_ * (width / 2)
            xs = [p.x + w.x, p.x - w.x, far.x + w.x, far.x - w.x]; ys = [p.y + w.y, p.y - w.y, far.y + w.y, far.y - w.y]
            self.obstacles.append((min(xs), max(xs), min(ys), max(ys), 0, 0))
            self.stats["main_aisles"] = self.stats.get("main_aisles", 0) + 1
            return

    def _pod_grid(self):
        """Open office as a system (critic r1/r2 2026-10-16: pods planned 'corner'/'against_wall' lost their wall-side seats or failed,
        leaving sled chairs facing a wall): identical pods in aligned rows -- desks, a chair zone each side, a 1 m aisle between chair
        zones, the wall-side chair zone doubling as the walkway -- the main aisle from the door kept clear, a task chair at every seat.
        Rows are swept across the room in 0.25 m steps (a row pitch apart once one lands) and pods packed greedily along each row, so
        they flank the aisle and the glass room; both orientations are dry-run and the one that seats more wins (office r3: a fixed
        grid placed 0-1 pods on a 70 m2 floor)."""
        from room_planner import proc_assets as pa
        self._main_aisle()
        x0, x1, y0, y1 = self.room.box
        # pods sized to the room: 2 desks a side under 12 m, else 3 (a 4-desk 5.6 m pod fitted nowhere beside a glass room, office r3)
        P = pa.WorkstationPodFactory(self.rng.randrange(1 << 24), n=2 if max(x1 - x0, y1 - y0) < 12 else 3).spawn_asset(
            self.stats["furniture_added"])
        front = fr.INF_FRONT
        bpy.context.view_layer.update()
        L, D = P.dimensions[1], P.dimensions[0]                  # length along local y, two desks deep along local x
        # 0.8 m chair zones, 0.9 m between facing chair zones, outer chair zones back onto the wall, pods 1.0 m apart with 0.6 m end
        # clearance: with 0.85/1.0/+0.1/1.2/0.9 a 10.3 x 7 m floor held one pod beside its glass room and door aisle (office r3)
        hz, row_pitch = D / 2 + 0.8, D + 2 * 0.8 + 0.9
        mv = hz + 0.02

        def layout(along_x):
            # Each row position (0.25 m steps) gets its best packing: pods greedily from every start offset, 1.0 m between pod ends,
            # the start that seats most wins. Rows are then chosen by a 1-D DP so facing chair zones keep a 0.9 m aisle (row pitch).
            # Greedy-from-the-wall took a 1-pod row and lost the second row on a 10.3 x 7 m floor (office r3).
            U, V = ((x1 - x0), (y1 - y0)) if along_x else ((y1 - y0), (x1 - x0))

            def box(u, v):
                bx = (u - L / 2, u + L / 2, v - hz, v + hz)
                f = (x0 + bx[0], x0 + bx[1], y0 + bx[2], y0 + bx[3]) if along_x else (x0 + bx[2], x0 + bx[3], y0 + bx[0], y0 + bx[1])
                return (*f, self.room.z, self.room.z + 1.2)

            def ok(u, v):
                f = box(u, v)
                cs = [(f[0] + 0.05, f[2] + 0.05), (f[1] - 0.05, f[2] + 0.05), (f[0] + 0.05, f[3] - 0.05), (f[1] - 0.05, f[3] - 0.05)]
                return not any(fr._overlap(f, ob) for ob in self.obstacles) and all(self.room.on_floor(*c) for c in cs)

            us = [0.6 + L / 2 + 0.25 * k for k in range(int((U - 1.2 - L) / 0.25) + 1)]
            rows = []
            for k in range(int((V - 2 * mv) / 0.25) + 1):
                v = mv + 0.25 * k
                free = [u for u in us if ok(u, v)]
                best = []
                for s0 in free:
                    run, last = [], None
                    for u in free:
                        if u >= s0 and (last is None or u - last >= L + 1.0 - 1e-6):
                            run.append(u); last = u
                    best = max(best, run, key=len)
                rows.append((v, best))
            score, pick = [0] * (len(rows) + 1), [[] for _ in range(len(rows) + 1)]
            for i, (v, best) in enumerate(rows, 1):
                j = max([k for k in range(i) if k == 0 or rows[k - 1][0] <= v - row_pitch + 1e-6])
                take = score[j] + len(best)
                score[i], pick[i] = (take, pick[j] + [(v, best)]) if take > score[i - 1] else (score[i - 1], pick[i - 1])
            return [((f[0] + f[1]) / 2, (f[2] + f[3]) / 2) for v, best in pick[-1] for f in [box(u, v) for u in best]]

        plans = {ax: layout(ax) for ax in (True, False)}
        along_x = max(plans, key=lambda ax: (len(plans[ax]), ax == ((x1 - x0) >= (y1 - y0))))
        yaw = (0.0 if along_x else math.pi / 2) + math.pi / 2
        added = 0
        for x, y in plans[along_x]:
            o = P.copy(); o.data = P.data; bpy.context.scene.collection.objects.link(o)   # identical pods share one mesh
            o.name = f"WorkstationPodFactory(grid{added}).spawn_asset({self.stats['furniture_added']})"
            if not fr._place(o, x, y, yaw, self.room, self.obstacles, front):
                bpy.data.objects.remove(o, do_unlink=True)
                continue
            pid = f"grid_pod{added}"
            self.ids[pid] = (o, front); self.stats["furniture_added"] += 1; added += 1
            self._pod_chairs(o)
            for _ in range(self.rng.randint(3, 6)):              # a few things at every seat (floor C r10: 'bench desks fairly bare',
                self.lived_in({"category": self.rng.choice(("mug", "mug", "paper_stack", "paper_stack", "takeaway_cup", "phone",
                                                            "notebook", "small_plant")), "on": pid})   # use 6, 3 of 3)
        bpy.data.objects.remove(P, do_unlink=True)              # the template; its mesh stays with the copies
        self.stats["grid_pods"] = added; self.pods_placed = added
        _log(f"pod grid: {added} pods ({len(plans[True])} along x / {len(plans[False])} along y, pod {L:.1f} x {D:.1f} m)")
        if added < 3:                                            # few pods: say what blocked the floor
            _log(f"pod grid sparse: box {[round(c, 2) for c in self.room.box]} obstacles {[[round(c, 1) for c in ob[:4]] for ob in self.obstacles]}")

    def _fill_lab_corridor(self, plan):
        """Research corridor (ROOM_LAB=1, rooms of type hallway): equipment chambers and gas cylinder racks side by side along the long wall with the fewer doors, clear of the door spans
        (the other wall keeps its doors); the corridor stays >= 1.6 m wide. Ref: lab_corridor_0127 frames 01, 02, 05, 07 (floor N r1: no chamber or rack ever reached the corridor)."""
        if not self.walls:
            return 0
        longs = sorted(self.walls, key=lambda k: -self.walls[k][3])[:2]
        n_doors = {k: sum(1 for dd in self.doc.get("doors", []) if dd.get("wall") == k) for k in longs}
        wid = min(longs, key=lambda k: n_doors[k])
        spans = [(dd["at_m"] - 0.95, dd["at_m"] + 0.95) for dd in self.doc.get("doors", []) if dd.get("wall") == wid]
        length = self.walls[wid][3]
        seq = ("lab_chamber", "lab_chamber", "gas_rack", "lab_chamber", "gas_rack", "lab_chamber", "lab_chamber", "gas_rack")
        s_, placed, k = 1.0, 0, 0
        while s_ < length - 1.2 and k < 14:
            cat = seq[k % len(seq)]; k += 1
            o, front = self._make(cat)
            if o is None:
                break
            bpy.context.view_layer.update()
            w, d = o.dimensions[1], o.dimensions[0]
            hit = next((b1 for b0, b1 in spans if s_ - 0.05 < b1 and s_ + w + 0.05 > b0), None)
            if hit is not None:                                  # a door span: jump past it
                bpy.data.objects.remove(o, do_unlink=True); s_ = hit + 0.1
                continue
            ok = any(fr._place(o, x, y, yw, self.room, self.obstacles, front) for x, y, yw in self._along_wall(wid, w, d, [s_ + w / 2]))
            if ok:
                self.ids[f"lab_{placed}"] = (o, front); self.stats["furniture_added"] += 1; placed += 1; s_ += w + 0.25
            else:
                bpy.data.objects.remove(o, do_unlink=True); s_ += 0.6
        self.stats["lab_corridor"] = {"placed": placed, "wall": wid, "length": round(length, 1)}
        return placed

    def _fill_mode(self, plan):
        """ROOM_MODE=<name>: room_planner/<name>_layout.py (layout(x0, x1, y0, y1, seed, obstacles, doors) -> {"items": [{cat, x, y, yaw, lift?, direct?}], "hung": [{cat, x, y, drop}],
        "settings": [{x, y, yaw, z}]}; module constants CATS = layout cat -> catalog cat, DROP = plan categories to drop). Items are placed like the other modes; returns the module."""
        import importlib
        lm = importlib.import_module("room_planner." + self.mode + "_layout")
        x0, x1, y0, y1 = self.room.box
        doors, cols = self._hall_keepouts()
        lay = lm.layout(x0, x1, y0, y1, self.rng.randrange(1 << 20), obstacles=cols, doors=doors)
        placed, failed, dress_ = 0, {}, []
        for e in lay["items"]:
            o, front = self._make(lm.CATS.get(e["cat"], e["cat"]))
            if o is None:
                failed.setdefault(e["cat"], 0); failed[e["cat"]] += 1
                continue
            if e.get("direct"):
                o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, e["yaw"]); o.location = (e["x"], e["y"], self.room.z + 0.002 + e.get("lift", 0.0))
                placed += 1
            elif fr._place(o, e["x"], e["y"], e["yaw"], self.room, self.obstacles, front):
                o.location.z += e.get("lift", 0.0)
                placed += 1; self.stats["furniture_added"] += 1
                if e["cat"] == "casual_table" and os.environ.get("ROOM_LOUNGE_DRESS") == "1":
                    self.ids[f"mode_ct{placed}"] = (o, front); dress_.append(f"mode_ct{placed}")
            else:
                failed.setdefault(e["cat"], 0); failed[e["cat"]] += 1
                bpy.data.objects.remove(o, do_unlink=True)
        self.toss = getattr(self, "toss", [])
        self.mode_dress = dress_                                 # S29F r7 D8: dressed after the plan's toss list is reset (run)
        zc = max((self.room.wall.matrix_world @ Vector(c)).z for c in self.room.wall.bound_box)
        hung = 0
        for c in lay.get("hung", []):
            o, _fr = self._make(lm.CATS.get(c["cat"], c["cat"]))
            if o is not None:
                o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, c.get("yaw", 0.0)); o.location = (c["x"], c["y"], zc - c.get("drop", 0.3)); hung += 1
        sets = 0
        for st in lay.get("settings", []):
            o, _fr = self._make("rt_setting")
            if o is not None:
                o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, st["yaw"]); o.location = (st["x"], st["y"], self.room.z + st["z"] + 0.002); sets += 1
        self.stats["mode_" + self.mode] = {"placed": placed, "wanted": len(lay["items"]), "failed": failed, "hung": hung, "settings": sets}
        return lm

    def _fill_pods(self, plan):
        """Open office: aligned pods (length along the long wall, no random yaw) into every empty region big enough, after the main
        aisle is reserved; each with its task chairs."""
        self._main_aisle()
        ox, oy = self.doc["_origin"]
        x0, x1, y0, y1 = self.room.box
        yaw = 0.0 if (x1 - x0) >= (y1 - y0) else math.pi / 2
        added = 0
        for k in range(8):
            regs = [r for r in self.report(plan, [])["empty_floor"] if r["area_m2"] >= 7.0]
            if not regs:
                break
            r = regs[0]
            cx, cy = ox + sum(r["x_range"]) / 2, oy + sum(r["y_range"]) / 2
            o, front = self._make("pod_unit")
            if o is None or not fr._place(o, cx, cy, yaw + math.pi / 2, self.room, self.obstacles, front):
                if o is not None:
                    bpy.data.objects.remove(o, do_unlink=True)
                self.obstacles.append((cx - 0.5, cx + 0.5, cy - 0.5, cy + 0.5, 0, 0))
                continue
            self._pod_chairs(o)
            added += 1
        self.stats["filled_pods"] = added
        _log(f"fill_pods: +{added}")

    def _fill_tables(self, plan, table, chair, min_m2):
        """The largest empty region >= min_m2 gets a table with chairs around it, until none is left."""
        ox, oy = self.doc["_origin"]
        added = 0
        for k in range(6):
            regs = [r for r in self.report(plan, [])["empty_floor"] if r["area_m2"] >= min_m2]
            if not regs:
                break
            r = regs[0]
            cx, cy = ox + sum(r["x_range"]) / 2, oy + sum(r["y_range"]) / 2
            o, front = self._make(table)
            cand = [(cx + dx, cy + dy, yw) for dx in (0, 0.4, -0.4, 0.8, -0.8) for dy in (0, 0.4, -0.4, 0.8, -0.8)
                    for yw in (0.0, math.pi / 2)]                 # an L-shaped region's centre is often not free (pantry r2: +0)
            if o is None or not any(fr._place(o, x, y, yw, self.room, self.obstacles, front) for x, y, yw in cand):
                if o is not None:
                    bpy.data.objects.remove(o, do_unlink=True)
                self.obstacles.append((cx - 0.5, cx + 0.5, cy - 0.5, cy + 0.5, 0, 0))
                continue
            tid = f"fill_{table}{k}"
            self.ids[tid] = (o, front); self.stats["furniture_added"] += 1; added += 1
            self.pending_ids = set()
            self.furniture({"id": tid + "c", "category": chair, "relation": "around", "target": tid, "count": 4})
        _log(f"fill {table}: +{added}")

    def _working_floor(self, boxes=True):
        """Signs of a working day on a warehouse floor (warehouse r9, signs of use 4-5: 'clean racks, one cart'): a hand truck and a step
        ladder against walls, and a few loose cartons by them, wherever they fit."""
        from room_planner import proc_assets as pa
        n = 0
        kinds = (pa.HandTruckFactory, pa.StepLadderFactory) + ((pa.CardboardBoxFactory, pa.CardboardBoxFactory) if boxes else ()) + (pa.HandTruckFactory,)
        for cls in kinds:
            o = cls(self.rng.randrange(1 << 24)).spawn_asset(self.stats["furniture_added"] + n)
            bpy.context.view_layer.update()
            w, d = o.dimensions[1], o.dimensions[0]
            spots = self.spots({"relation": "against_wall"}, w, d)
            self.rng.shuffle(spots)
            x0, x1, y0, y1 = self.room.box                       # walls are rack-lined in a storage hall (r10: +0 placed): any free floor
            spots = spots[:25] + [(self.rng.uniform(x0, x1), self.rng.uniform(y0, y1), self.rng.uniform(0, 6.28)) for _ in range(60)]
            yaw_j = self.rng.uniform(-0.6, 0.6)
            if any(fr._place(o, x, y, yaw + yaw_j, self.room, self.obstacles, fr.INF_FRONT) for x, y, yaw in spots):
                n += 1
            else:
                bpy.data.objects.remove(o, do_unlink=True)
        self.stats["working_floor"] = n
        _log(f"working floor: +{n}")

    def _rack_aisles(self, aisle=2.6, center_row=False):
        """Warehouse floor as aisles (warehouse r5: 'racks scattered across the hall at mixed orientations'): rows of racks parallel to
        the long axis, a rack depth plus a pallet-truck aisle apart, each row filled bay by bay from one end; a bay that collides
        (door zone, existing furniture) is skipped, so a row can have gaps but never turns."""
        x0, x1, y0, y1 = self.room.box
        long_x = (x1 - x0) >= (y1 - y0)
        L0, L1, S0, S1 = (x0, x1, y0, y1) if long_x else (y0, y1, x0, x1)
        yaw = math.pi / 2 if long_x else 0.0                    # rack length (local y) along the long axis
        k, v = 0, ((S0 + S1) / 2 if center_row else S0 + 1.4)   # center_row: one free-standing row on the long centre line (a packing
        while v < S1 - 1.0:                                      # room with wall racks; wh r24: 'one rack line, no aisles', 3 of 3)
            u = L0 + 1.2
            while u < L1 - 1.2:
                o, front = self._make("storage_rack")
                if o is None:
                    break
                bay = o.dimensions[1]
                x, y = (u + bay / 2, v) if long_x else (v, u + bay / 2)
                if fr._place(o, x, y, yaw, self.room, self.obstacles, front):
                    self.ids[f"aisle_{k}"] = (o, front); self.stats["furniture_added"] += 1; k += 1
                else:
                    bpy.data.objects.remove(o, do_unlink=True)
                u += bay + 0.08                                  # _overlap keeps 0.05 m: at exactly 0.05 every second bay 'collided' and
                # rows read as lone units with gaps (floor J r14: 'freestanding singles, not aisles', layout 5, 3 of 3)
            v += 1.0 + aisle if not center_row else 1e9          # rack depth (<= 1.0 m) plus the pallet-truck aisle
        _log(f"rack aisles: +{k} bays")

    def _fill_items(self, plan, cats, min_m2, limit=8, face=None):
        """The largest empty region >= min_m2 gets the next of `cats` (cycling), offsets tried around its centre, until none is left.
        face=(x, y): each item's front turned toward that point, snapped to the walls' axes."""
        ox, oy = self.doc["_origin"]
        added = 0
        for k in range(8):
            if added >= limit:
                break
            regs = [r for r in self.report(plan, [])["empty_floor"] if r["area_m2"] >= min_m2]
            if not regs:
                break
            r = regs[0]
            cx, cy = ox + sum(r["x_range"]) / 2, oy + sum(r["y_range"]) / 2
            o, front = self._make(cats[k % len(cats)])
            q = math.pi / 2
            # the whole region on a 0.3 m grid, centre first: +-0.8 m round the centre of an L-shaped 22 m2 gym region missed it
            # (floor F3 r13: bike, exercise set and mats all '+0')
            pts = sorted(((ox + x, oy + y) for x in _frange(r["x_range"][0], r["x_range"][1], 0.3) for y in _frange(r["y_range"][0], r["y_range"][1], 0.3)),
                         key=lambda p_: (p_[0] - cx) ** 2 + (p_[1] - cy) ** 2)[:60]
            cand = [(x, y, yw) for x, y in pts
                    for yw in ((round(math.atan2(face[1] - y, face[0] - x) / q) * q,) if face else (0.0, q))]
            if o is None or not any(fr._place(o, x, y, yw, self.room, self.obstacles, front) for x, y, yw in cand):
                if o is not None:
                    bpy.data.objects.remove(o, do_unlink=True)
                self.obstacles.append((cx - 0.5, cx + 0.5, cy - 0.5, cy + 0.5, 0, 0))
                continue
            self.ids[f"fill_i{k}"] = (o, front); self.stats["furniture_added"] += 1; added += 1
        _log(f"fill items {cats}: +{added}")

    def _hall_keepouts(self):
        """Door points (world xy) and column / pilaster footprints (xmin, xmax, ymin, ymax) for the deterministic hall layouts."""
        doors = []
        for dd in self.doc.get("doors", []):
            if dd["wall"] in self.walls:
                p = self.walls[dd["wall"]][0] + self.walls[dd["wall"]][1] * dd["at_m"]
                doors.append((p.x, p.y))
        cols = [fr.footprint(o)[:4] for o in bpy.data.objects if o.type == "MESH" and ("Column" in o.name or "Pilaster" in o.name)]
        return doors, cols

    def _fill_clinic_lobby(self, plan):
        """Clinic reception lobby (ROOM_CLINIC_LOBBY=1): room_planner/clinic_lobby_layout places the oak wall, louver desk, seating group on a jute rug, plants and art."""
        from room_planner import clinic_lobby_layout as cll
        x0, x1, y0, y1 = self.room.box
        doors, cols = self._hall_keepouts()
        lay = cll.layout(x0, x1, y0, y1, self.rng.randrange(1 << 20), obstacles=cols, doors=doors)
        placed, failed, by_cat = 0, {}, {}
        for e in lay["items"]:
            o, front = self._make(LOBBY_CATS[e["cat"]])
            if o is None:
                failed.setdefault(e["cat"], {}).setdefault("spawn_failed", 0)
                failed[e["cat"]]["spawn_failed"] += 1
                continue
            if e.get("direct"):                                   # the rug lies under the seating group: no footprint check
                o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, e["yaw"]); o.location = (e["x"], e["y"], self.room.z + 0.002)
                placed += 1; by_cat[e["cat"]] = by_cat.get(e["cat"], 0) + 1
            elif fr._place(o, e["x"], e["y"], e["yaw"], self.room, self.obstacles, front):
                o.location.z += e.get("lift", 0.0)
                placed += 1; self.stats["furniture_added"] += 1; by_cat[e["cat"]] = by_cat.get(e["cat"], 0) + 1
            else:
                why = self._why_not_placed({**e, "cat": e["cat"]}, doors, cll)
                failed.setdefault(e["cat"], {}).setdefault(why, 0)
                failed[e["cat"]][why] += 1
                bpy.data.objects.remove(o, do_unlink=True)
        self.stats["clinic_lobby"] = {"placed": placed, "wanted": len(lay["items"]), "by_cat": by_cat, "failed": failed, "far_wall": lay["far_wall"]["normal"], "doors": [[round(d[0], 1), round(d[1], 1)] for d in doors]}
        return placed

    def _fill_museum(self, plan):
        """Science museum (ROOM_MUSEUM=1): room_planner/museum_layout places the rotunda's parapet ring, lit scale ring and pendulum (hung from the dome crown), the element
        showcase wall with the nebula panel and marble benches, and the lit pictures; the dome shell itself comes from museum_shell via the 'museum' archetype."""
        from room_planner import museum_layout as ml
        x0, x1, y0, y1 = self.room.box
        lay = ml.layout(x0, x1, y0, y1, self.rng.randrange(1 << 20))
        zc = max((self.room.wall.matrix_world @ Vector(c)).z for c in self.room.wall.bound_box)
        placed, failed, by_cat = 0, {}, {}
        for e in lay["items"]:
            o, front = self._make(MUSEUM_CATS[e["cat"]])
            if o is None:
                failed.setdefault(e["cat"], {}).setdefault("spawn_failed", 0)
                failed[e["cat"]]["spawn_failed"] += 1
                continue
            if e.get("direct"):                                   # ring / pendulum: placed at the rotunda centre, no footprint check
                o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, e["yaw"])
                o.location = (e["x"], e["y"], (zc - 0.3) if e.get("hang") else self.room.z + 0.002 + e.get("lift", 0.0))
                placed += 1; by_cat[e["cat"]] = by_cat.get(e["cat"], 0) + 1
            elif fr._place(o, e["x"], e["y"], e["yaw"], self.room, self.obstacles, front):
                o.location.z += e.get("lift", 0.0)
                placed += 1; self.stats["furniture_added"] += 1; by_cat[e["cat"]] = by_cat.get(e["cat"], 0) + 1
            else:
                why = self._why_not_placed({**e}, [], ml)
                failed.setdefault(e["cat"], {}).setdefault(why, 0)
                failed[e["cat"]][why] += 1
                bpy.data.objects.remove(o, do_unlink=True)
        self.stats["museum"] = {"placed": placed, "wanted": len(lay["items"]), "by_cat": by_cat, "failed": failed, "rotunda": lay["rotunda"]}
        return placed

    def _fill_winepub(self, plan):
        """Wine pub (ROOM_WINEPUB=1): room_planner/winepub_layout places the bar, bottle shelves, floor-edge bottle rows, round marble tables with velvet chairs and
        the mirror wall; mirror ball and silver spheres hang from the soffit (winepub_ceiling supplies the ceiling itself)."""
        from room_planner import winepub_layout as wl, proc_winepub as wp
        x0, x1, y0, y1 = self.room.box
        doors, cols = self._hall_keepouts()
        lay = wl.layout(x0, x1, y0, y1, self.rng.randrange(1 << 20), obstacles=cols, doors=doors)
        placed, failed, bar_placed = 0, {}, False
        for e in lay["items"]:
            o, front = self._make(WINEPUB_CATS[e["cat"]])
            if o is None:
                failed.setdefault(e["cat"], {}).setdefault("spawn_failed", 0)
                failed[e["cat"]]["spawn_failed"] += 1
                continue
            if fr._place(o, e["x"], e["y"], e["yaw"], self.room, self.obstacles, front):
                placed += 1; self.stats["furniture_added"] += 1
                bar_placed = bar_placed or e["cat"] == "bar_counter"
            else:
                why = self._why_not_placed(e, doors, wl)
                failed.setdefault(e["cat"], {}).setdefault(why, 0)
                failed[e["cat"]][why] += 1
                bpy.data.objects.remove(o, do_unlink=True)
        zc = max((self.room.wall.matrix_world @ Vector(c)).z for c in self.room.wall.bound_box)
        hung = 0
        for c in lay["ceiling"]:
            cls = wp.MirrorBallFactory if c["cat"] == "mirror_ball" else wp.SilverSphereClusterFactory
            o = cls(self.rng.randrange(1 << 20)).spawn_asset(hung)
            o.location = (c["x"], c["y"], zc - 0.35); hung += 1
        sets = 0
        for st in lay.get("settings", []):                       # a dish and a glass at every seat (S23 r4: 'bare tables')
            o, _front = self._make("rt_setting")
            if o is None:
                continue
            o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, st["yaw"]); o.location = (st["x"], st["y"], self.room.z + st["z"] + 0.002)
            sets += 1
        self.stats["winepub_settings"] = sets
        self._table_ware_all()                                   # plate + glass + candle on every table, bar-height ones too (S23 r6 CNT-01)
        self._pair_chairs()                                      # every chair faces its table
        self.stats["winepub"] = {"placed": placed, "wanted": len(lay["items"]), "ceiling_items": hung, "failed": failed, "bar_placed": bar_placed}
        return placed

    def _fill_rooftop(self, plan):
        """Rooftop fine-dining restaurant (ROOM_ROOFTOP=1): room_planner/rooftop_layout places banquettes, velvet booths, marble tables with
        stools, mirror columns, air conditioners and heaters; a table setting on every table; Poly Haven chandeliers (needs the Poly Haven
        index in ROOM_EXTRA_ASSET_INDEXES, else skipped) made emissive by rooftop_shell.light_chandelier."""
        from room_planner import rooftop_layout as rl, rooftop_shell as rs
        x0, x1, y0, y1 = self.room.box
        doors, cols = self._hall_keepouts()
        lay = rl.layout(x0, x1, y0, y1, self.rng.randrange(1 << 20), obstacles=cols, doors=doors)
        placed, failed, counter_placed = 0, {}, False
        for e in lay["items"]:
            cat = f"rt_stool_{e.get('kind', 'white')}" if e["cat"] == "bar_stool" else ROOFTOP_CATS[e["cat"]]
            o, front = self._make(cat)
            if o is None:
                failed.setdefault(e["cat"], {}).setdefault("spawn_failed", 0)
                failed[e["cat"]]["spawn_failed"] += 1
                continue
            if fr._place(o, e["x"], e["y"], e["yaw"], self.room, self.obstacles, front):
                placed += 1; self.stats["furniture_added"] += 1
                counter_placed = counter_placed or e["cat"] == "counter"
            else:
                why = self._why_not_placed(e, doors, rl)
                failed.setdefault(e["cat"], {}).setdefault(why, 0)
                failed[e["cat"]][why] += 1
                bpy.data.objects.remove(o, do_unlink=True)
        sets = 0
        for st in lay["settings"]:
            o, _front = self._make("rt_setting")
            if o is None:
                continue
            o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, st["yaw"]); o.location = (st["x"], st["y"], self.room.z + st["z"] + 0.002)
            sets += 1
        chand = 0
        try:
            import abo_assets as abo
            pool = [e for e in abo.entries() if e["id"] in ROOFTOP_CHANDELIERS]
            for c in lay["chandeliers"] if pool else ():
                e = self.rng.choice(pool)
                o = abo._import(e, f"RooftopChandelier({e['id']}).spawn_asset({chand})")
                o.rotation_mode = "XYZ"; o.location = (c["x"], c["y"], self.room.z + c["z"] - o.dimensions[2] / 2)
                rs.light_chandelier(o)
                chand += 1
        except Exception as ex:                                   # noqa: BLE001 -- chandeliers are an optional extra
            self.stats["rooftop_chandelier_error"] = str(ex)[:80]
        self.stats["rooftop"] = {"placed": placed, "wanted": len(lay["items"]), "settings": sets, "chandeliers": chand, "failed": failed,
                                 "counter_placed": counter_placed}
        return placed

    def _why_not_placed(self, e, doors, mod=None):
        """Best-effort reason a layout piece was refused by furnish_rooms._place: 'door' (inside a door keep-out), 'obstacle' (overlaps a placed
        footprint) or 'off_floor' (the rest: a corner off the floor mesh)."""
        from room_planner import flagship_layout as fll
        fll = mod or fll                                         # any layout module with SIZE and DOOR_CLEAR (flagship_layout, rooftop_layout)
        d, l = fll.SIZE.get(e["cat"], (0.6, 1.0))
        c, s = abs(math.cos(e["yaw"])), abs(math.sin(e["yaw"]))
        hx, hy = (d * c + l * s) / 2, (d * s + l * c) / 2
        b = (e["x"] - hx, e["x"] + hx, e["y"] - hy, e["y"] + hy)
        if any(abs(e["x"] - dx) < fll.DOOR_CLEAR and abs(e["y"] - dy) < fll.DOOR_CLEAR for dx, dy in doors):
            return "door"
        if any(fr._overlap(b, ob) for ob in self.obstacles):
            return "obstacle"
        return "off_floor"

    def _fill_flagship(self, plan):
        """Flagship hall (ROOM_FLAGSHIP=1, area > 150 m2): a deterministic plan from room_planner/flagship_layout, placed piece by piece (the region
        finder of _fill_boutique is sized for rooms, not halls). Doors and column / pilaster footprints are kept clear."""
        from room_planner import flagship_layout as fll
        x0, x1, y0, y1 = self.room.box
        doors, cols = self._hall_keepouts()
        lay = fll.layout(x0, x1, y0, y1, self.rng.randrange(1 << 20), obstacles=cols, doors=doors)
        placed, failed, counter_placed = 0, {}, False
        for e in lay["items"]:
            o, front = self._make(e["cat"])
            if o is None:
                continue
            if fr._place(o, e["x"], e["y"], e["yaw"], self.room, self.obstacles, front):
                o.location.z += e.get("lift", 0.0)
                placed += 1; self.stats["furniture_added"] += 1
                counter_placed = counter_placed or e["cat"] == "counter"
            else:
                why = self._why_not_placed(e, doors)
                failed.setdefault(e["cat"], {}).setdefault(why, 0)
                failed[e["cat"]][why] += 1
                failed[e["cat"]].setdefault("at", []).append([round(e["x"] - x0, 1), round(e["y"] - y0, 1)])   # room-frame position of each refusal
                bpy.data.objects.remove(o, do_unlink=True)
        self.stats["flagship_layout"] = {"placed": placed, "wanted": len(lay["items"]), "failed": failed, "counter_placed": counter_placed}
        return placed

    def _fill_bookstore(self, plan):
        """Bookstore (ROOM_BOOKSTORE=1): wall shelving, book islands in rows, pop-up tables and section signs from room_planner/bookstore_layout."""
        from room_planner import bookstore_layout as bl
        x0, x1, y0, y1 = self.room.box
        doors, cols = self._hall_keepouts()
        lay = bl.layout(x0, x1, y0, y1, self.rng.randrange(1 << 20), obstacles=cols, doors=doors)
        placed, failed, wanted = 0, {}, 0
        for key, cat in (("wall_shelves", "book_wall_shelf"), ("islands", "book_island"), ("popups", "book_island"), ("signs", "section_sign"), ("pop_stands", "book_pop"),
                          ("bestsellers", "bestseller_table"), ("best_signs", "bestseller_sign"), ("posters", "wall_poster")):
            for e in lay[key]:
                wanted += 1
                o, front = self._make(cat)
                if o is None:
                    failed.setdefault(cat, {}).setdefault("spawn_failed", 0)
                    failed[cat]["spawn_failed"] += 1
                    continue
                if fr._place(o, e["x"], e["y"], e["yaw"], self.room, self.obstacles, front):
                    o.location.z += e.get("lift", 0.0)                # wall posters hang at 0.9 m
                    placed += 1; self.stats["furniture_added"] += 1
                else:
                    why = self._why_not_placed({**e, "cat": cat}, doors, bl)
                    failed.setdefault(cat, {}).setdefault(why, 0)
                    failed[cat][why] += 1
                    failed[cat].setdefault("at", []).append([round(e["x"] - x0, 1), round(e["y"] - y0, 1)])
                    bpy.data.objects.remove(o, do_unlink=True)
        self.stats["bookstore"] = {"placed": placed, "wanted": wanted, "failed": failed, "zones": sorted({e["zone"] for k in ("islands", "wall_shelves") for e in lay[k]})}
        return placed

    def _fill_boutique(self, plan):
        """Boutique floor: the largest empty region >= 3 m2 gets a display table or a clothing rack (alternating), until none is left."""
        if BOOKSTORE or MUSEUM:                                  # already placed first in run()
            return 0
        if FLAGSHIP and self.doc.get("area_m2", 0) > 150:        # already placed first in run()
            return 0
        ox, oy = self.doc["_origin"]
        added = 0
        for _ in range(8 if FLAGSHIP else int(proc_assets_kit().STYLE.get("wall_rails", 0))):   # flat-bar wall rails along the free walls (a wall id can be 0: test for False); kit wall_rails: a non-flagship boutique's wall-length garment rows (S15)
            if self._wall_mount("wall_rail", self.WALL_MOUNTED["wall_rail"]) is False:
                break
        for sid, (o_, _) in list(self.ids.items()):             # planned wall gondolas are stocked (S15 r27 CNT-04: bare narrow shelving beside the fitting cubicles)
            if rd._factory(o_.name) in self.MERCH_HOSTS and ":" not in sid:
                self.fill({"on": sid, "category": "boutique_stock"}, None)
        for k in range(24 if FLAGSHIP else 10):
            regs = [r for r in self.report(plan, [])["empty_floor"] if r["area_m2"] >= 3.0]
            if not regs:
                break
            r = regs[0]
            cx, cy = ox + sum(r["x_range"]) / 2, oy + sum(r["y_range"]) / 2
            o, front = self._make(FLAGSHIP_CATS[k % 4] if FLAGSHIP else ("display_table" if k % 2 == 0 else "clothing_rack"))
            yaw = self.rng.choice((0.0, math.pi / 2))
            if o is None or not fr._place(o, cx, cy, yaw, self.room, self.obstacles, front):
                if o is not None:
                    bpy.data.objects.remove(o, do_unlink=True)
                self.obstacles.append((cx - 0.5, cx + 0.5, cy - 0.5, cy + 0.5, 0, 0))
                continue
            self.ids[f"fill_b{k}"] = (o, front); self.stats["furniture_added"] += 1; added += 1
        _log(f"fill_boutique: +{added}")

    def _waiting_island(self, plan):
        """Two bench rows facing each other across a low table, placed as one group in the largest empty region (floor D3 r10: the
        table placed, then both benches found no 'in_front_of' spot -- 'two short rows and a coffee table', 3 of 3)."""
        from room_planner import proc_assets as pa
        ox, oy = self.doc["_origin"]
        n_obs = len(self.obstacles)
        self._counter_lanes()
        regs = [r for r in self.report(plan, [])["empty_floor"] if r["area_m2"] >= 4.0]
        if not regs:
            return _log("waiting island: no region")
        lanes = self.obstacles[n_obs:]
        r = regs[0]
        cx, cy = ox + sum(r["x_range"]) / 2, oy + sum(r["y_range"]) / 2
        t = pa.ClinicLowTableFactory(self.rng.randrange(1 << 24)).spawn_asset(self.stats["furniture_added"])
        from room_planner import proc_home as _ph                # the shaped upholstered bench (F3 r27: the island's two rows were still the old moulded-slab WaitingBenchFactory; same object name, same colour pick)
        fb1, fb2 = _ph.UpholsteredBenchFactory(self.rng.randrange(1 << 24)), _ph.UpholsteredBenchFactory(self.rng.randrange(1 << 24))
        fb1.n = fb2.n = 3                                        # 3-seat rows: 5-seat ones found 'no fit' (floor F3 r11-r12)
        b1, b2 = fb1.spawn_asset(self.stats["furniture_added"] + 1), fb2.spawn_asset(self.stats["furniture_added"] + 2)
        bpy.context.view_layer.update()
        q = math.pi / 2
        # every 0.4 m of the room, nearest the largest empty region first: +-0.8 m around its centre found 'no fit' in a 44 m2 lobby
        # that was mostly bare floor (floor D3 r13: reception 6/5/7/4/3, 3 of 3)
        bx0, bx1, by0, by1 = self.room.box
        grid = sorted(((x, y) for x in _frange(bx0 + 1.0, bx1 - 1.0, 0.4) for y in _frange(by0 + 1.0, by1 - 1.0, 0.4)),
                      key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
        why = {"table": 0, "bench1": 0, "bench2": 0}
        # lanes first; a lobby with doors on three walls has no room left once every door's lane is kept (floor E3 r13: table 'no fit'
        # at 229 of 240 tries), so the second pass drops them -- an island beside the path beats an empty hall (D3 r13: 6/5/7/4/3)
        for pass_, (gx, gy) in [(0, p) for p in grid[:120]] + [(1, p) for p in grid[:120]]:
                if pass_ == 1 and lanes and self.obstacles[-len(lanes):] == lanes:
                    del self.obstacles[-len(lanes):]
                for yaw in (0.0, q):                             # the rows run along the table's long side (local y)
                    ax = Vector((math.cos(yaw), math.sin(yaw), 0))   # the across-the-table axis
                    c = Vector((gx, gy, 0))
                    trial = list(self.obstacles)
                    p1, p2 = c + ax * 0.95, c - ax * 0.95
                    ok_t = fr._place(t, c.x, c.y, yaw, self.room, trial, fr.INF_FRONT)
                    ok_1 = ok_t and fr._place(b1, p1.x, p1.y, yaw + math.pi, self.room, trial, fr.INF_FRONT)
                    ok_2 = ok_1 and fr._place(b2, p2.x, p2.y, yaw, self.room, trial, fr.INF_FRONT)
                    why["table" if not ok_t else "bench1" if not ok_1 else "bench2"] += not ok_2
                    if ok_2:
                        self.obstacles[:] = trial
                        for k, o in enumerate((t, b1, b2)):
                            self.ids[f"island_{k}"] = (o, fr.INF_FRONT)
                        self.stats["furniture_added"] += 3
                        # its magazines are part of the low table (floor F3 r13: a book_stack read as 'hardback heaps')
                        return _log(f"waiting island: placed{' (lanes dropped)' if pass_ else ''}")
        for o in (t, b1, b2):
            bpy.data.objects.remove(o, do_unlink=True)
        _log(f"waiting island: no fit {why} over {min(len(grid), 120)} spots, {len(self.obstacles)} obstacles")

    def _cafe_table_cap(self):
        return max(4, int(self.doc.get("area_m2", 40) / 13))     # one table per 13 m2 of hall, counter and aisles included (1 per 10:
                                                                 # 'tables edge to edge' still, floor G r13)

    def _counter_lanes(self):
        """A 1.2 m lane from every door to the counter front stays clear: a full floor of tables left no way to the queue (floor G r6:
        layout 5, 3 of 3); a shop floor's gondolas boxed the till in the same way (floor I r8)."""
        ctr = [_frame(*v) for v in self.ids.values() if rd._factory(v[0].name) in ("CafeCounterFactory", "CheckoutCounterFactory",
                                                                                   "ReceptionDeskFactory")]
        # a shop till and a clinic front desk too (floor E3 r12: the waiting island stood across the door-to-desk path, 3 of 3)
        if not ctr:
            return
        c_, f_, w_, d_ = ctr[0]
        q = c_ + f_ * (d_ / 2 + 0.8)
        for d0 in self.doc.get("doors", []):
            if d0["wall"] not in self.walls:
                continue
            a_, t_, n_, _ = self.walls[d0["wall"]]
            p_ = a_ + t_ * d0["at_m"] + n_ * 0.6
            seg = q - p_
            for i in range(int(seg.length / 0.4) + 1):
                m_ = p_ + seg * (i * 0.4 / max(seg.length, 1e-6))
                self.obstacles.append((m_.x - 0.6, m_.x + 0.6, m_.y - 0.6, m_.y + 0.6, 0, 0))

    def _lobby_stair(self, plan):
        """A stair flight on free floor (kit lobby_stair): the largest empty regions are tried with a grid of spots and the four turns; the footprint check keeps the door zones and the other pieces clear.
        Falls back to a 1.0 x 2.8 m flight (scaled) if the full one does not fit."""
        ox, oy = self.doc["_origin"]
        for scale in (1.0, 0.8):
            for k in range(4):
                regs = [r for r in self.report(plan, [])["empty_floor"] if r["area_m2"] >= 4.0 * scale]
                if not regs:
                    break
                o, front = self._make("staircase")
                if o is None:
                    return
                if scale < 1.0:
                    o.scale = (scale, scale, scale)
                    bpy.context.view_layer.update()
                done = False
                for r in regs[:3]:
                    cx, cy = ox + sum(r["x_range"]) / 2, oy + sum(r["y_range"]) / 2
                    hx, hy = (r["x_range"][1] - r["x_range"][0]) / 2, (r["y_range"][1] - r["y_range"][0]) / 2
                    pts = [(cx + fx * hx, cy + fy * hy) for fx in (0, -0.4, 0.4, -0.7, 0.7) for fy in (0, -0.4, 0.4, -0.7, 0.7)]
                    for yaw in (0.0, math.pi / 2, math.pi, -math.pi / 2):
                        if any(fr._place(o, x_, y_, yaw, self.room, self.obstacles, front) for x_, y_ in pts):
                            done = True
                            break
                    if done:
                        break
                if done:
                    self.ids["stair"] = (o, front); self.stats["furniture_added"] += 1
                    self.stats["lobby_stair"] = {"scale": scale}
                    _log(f"lobby stair placed (scale {scale})")
                    return
                bpy.data.objects.remove(o, do_unlink=True)
                break
        self.stats["lobby_stair"] = None
        _log("lobby stair: no free-floor spot")

    def _fill_gondolas(self, plan):
        """Grocery sales floor: the largest empty region >= 3 m2 gets a double gondola parallel to the long wall, stocked with facings,
        until none is left (user 2026-10-16: an empty centre reads as a stockroom)."""
        self._balloon()                                                          # promo letter balloons on a free wall (user 2026-10-17)
        for sid, (o, _) in list(self.ids.items()):               # a dispensing wall behind the counter is stocked too (shop r2: 'floating
            if rd._factory(o.name) == "BackBarShelfFactory" and ":" not in sid:   # wooden boards with nothing on them')
                self.fill({"on": sid, "category": "groceries"}, _cls(catalog.LIVED_IN["groceries"]["src"]))
        for sid, (o, _) in list(self.ids.items()):               # planned gondolas / wall gondolas are stocked too: their plan entries carry no fill flag, so lived_in drops one item
            if rd._factory(o.name) in self.MERCH_HOSTS and ":" not in sid and not sid.startswith("fill_g"):      # (S16 r27/r28: wg_* bare, only fill_g0 stocked)
                self.fill({"on": sid, "category": "groceries"}, _cls(catalog.LIVED_IN["groceries"]["src"]))
        self._counter_lanes()
        for o_, _ in [v for v in self.ids.values() if rd._factory(v[0].name) in ("GondolaFactory", "WallGondolaFactory")]:
            f0 = fr.footprint(o_)                                # planned gondolas keep 0.6 m aisles too
            self.obstacles.append((f0[0] - 1.2, f0[1] + 1.2, f0[2] - 1.2, f0[3] + 1.2, 0, 0))
        ox, oy = self.doc["_origin"]
        x0, x1, y0, y1 = self.room.box
        yaw = 0.0 if (x1 - x0) >= (y1 - y0) else math.pi / 2          # gondola length (local y) along the long wall
        added = 0
        for k in range(10):
            regs = [r for r in self.report(plan, [])["empty_floor"] if r["area_m2"] >= 3.0]
            if not regs:
                break
            r = regs[0]
            cx, cy = ox + sum(r["x_range"]) / 2, oy + sum(r["y_range"]) / 2
            hx, hy = (r["x_range"][1] - r["x_range"][0]) / 2, (r["y_range"][1] - r["y_range"][0]) / 2
            # the region's box centre can sit on furniture in a large L-shaped region: try a grid across it (floor I r5: 70 m2 empty,
            # 'fill_gondolas: +0', a half-empty shop, 3 of 3)
            pts = [(cx + fx * hx, cy + fy * hy) for fx in (0, -0.3, 0.3, -0.6, 0.6) for fy in (0, -0.3, 0.3, -0.6, 0.6)]
            o, front = self._make("gondola")
            if o is None or not any(fr._place(o, x_, y_, yaw + math.pi / 2, self.room, self.obstacles, front) for x_, y_ in pts):
                if o is not None:
                    bpy.data.objects.remove(o, do_unlink=True)
                self.obstacles.append((cx - 0.4, cx + 0.4, cy - 0.4, cy + 0.4, 0, 0))
                continue
            gid = f"fill_g{k}"
            f0 = fr.footprint(o)                                 # 1.2 m aisles between runs (floor I r8: 'a gondola maze', layout 5, 3/3)  # the new run has no margin of its own: 0.6 gave 0.6 m aisles (floor I r15: 'under 1 m', 3/3)
            self.obstacles.append((f0[0] - 1.2, f0[1] + 1.2, f0[2] - 1.2, f0[3] + 1.2, 0, 0))
            self.ids[gid] = (o, front); self.copies = getattr(self, "copies", {}); self.copies[gid] = [(o, front)]
            self.stats["furniture_added"] += 1
            self.fill({"on": gid, "category": "groceries"}, _cls(catalog.LIVED_IN["groceries"]["src"]))
            added += 1
        self.stats["filled_gondolas"] = added
        _log(f"fill_gondolas: +{added}")

    def report(self, plan, failed) -> dict:
        """What the plan became, in the room frame: placed new items, items not placed (with why), empty floor, free wall."""
        ox, oy = self.doc["_origin"]
        rel = lambda v: [round(v.x - ox, 2), round(v.y - oy, 2)]  # noqa: E731
        placed = []
        for it in plan.get("furniture", []):
            if it["id"] in self.ids:
                c, f, w, d = _frame(*self.ids[it["id"]])
                placed.append({"id": it["id"], "category": it["category"], "center": rel(c), "size_wd": [round(w, 2), round(d, 2)],
                               "facing_deg": round(math.degrees(_yaw(f))) % 360})
        x0, x1, y0, y1 = self.room.box
        step = 0.4
        nx, ny = int((x1 - x0) / step), int((y1 - y0) / step)
        free = set()
        for i in range(nx):
            for j in range(ny):
                cx, cy = x0 + (i + 0.5) * step, y0 + (j + 0.5) * step
                cell = (cx - step / 2, cx + step / 2, cy - step / 2, cy + step / 2)
                if self.room.on_floor(cx, cy) and not any(fr._overlap(cell, b, m=0.0) for b in self.obstacles):
                    free.add((i, j))
        regions, seen = [], set()
        for c0 in sorted(free):
            if c0 in seen:
                continue
            comp, stack = [], [c0]
            seen.add(c0)
            while stack:
                i, j = stack.pop(); comp.append((i, j))
                for n in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                    if n in free and n not in seen:
                        seen.add(n); stack.append(n)
            area = len(comp) * step * step
            if area >= 1.0:
                xs = [x0 + (i + 0.5) * step for i, _ in comp]; ys = [y0 + (j + 0.5) * step for _, j in comp]
                regions.append({"area_m2": round(area, 1), "x_range": [round(min(xs) - ox, 1), round(max(xs) - ox, 1)],
                                "y_range": [round(min(ys) - oy, 1), round(max(ys) - oy, 1)]})
        regions.sort(key=lambda r: -r["area_m2"])
        free_wall = []
        for wid, (a, t_, n, length) in self.walls.items():
            run0 = None
            for k in range(int(length / 0.15) + 1):
                q = a + t_ * (k * 0.15) + n * 0.3
                ok = self.room.on_floor(q.x, q.y) and not any(b[0] <= q.x <= b[1] and b[2] <= q.y <= b[3] for b in self.obstacles)
                if ok and run0 is None:
                    run0 = k * 0.15
                if (not ok or k == int(length / 0.15)) and run0 is not None:
                    end = k * 0.15
                    if end - run0 >= 0.6:
                        free_wall.append({"wall": wid, "from_m": round(run0, 2), "to_m": round(end, 2)})
                    run0 = None
        return {"placed": placed, "not_placed": [{"id": it["id"], "category": it["category"], "relation": it["relation"],
                                                  "target": it.get("target") or it.get("wall"), "reason": why} for it, why in failed],
                "empty_floor": regions[:5], "free_floor_m2": round(len(free) * step * step, 1), "free_wall": free_wall}

    # parallel_bars before exam_table (the physio sort orders them): the couches took the floor first and the bars ran along them
    # (clinic r22/r23)
    FIRST = ("dock_door", "glass_meeting_room", "dental_chair", "parallel_bars", "exam_table", "reception_desk", "medical_cabinet", "clinic_desk")   # structure, then each room's hero piece                             # structure-like zones go before everything else

    REQUIRED_ZONE = {"break-room": ("pantry_run", "against_wall"), "meeting-room": ("meeting_set", "center"),
                     "cafe": ("coffee_bar", "against_wall"), "open-office": ("workstation_pod", "center")}

    CLUTTER = [("mug", 3), ("paper_stack", 3.5), ("pen_cup", 2), ("notebook", 2.5), ("takeaway_cup", 1.5), ("clipboard", 1),   # no snack
               # bowls: 'cereal/serving bowls on every private desk' (floor C r7)
               ("book_stack", 1), ("open_book", 0.7), ("phone", 1), ("small_plant", 0.4),
               ("open_laptop", 2.2), ("lanyard", 1.2), ("desk_plant", 1.0)]   # desk density (S2 A/B: laptop open, lanyard, plant)   # no bottle: the factory's
    # bottle reads as wine on a clinic manager's desk (floor D3 r21, 3 of 3)
    CAFE_CLUTTER = [("mug", 3), ("plate", 2.5), ("takeaway_cup", 2), ("phone", 1.5), ("notebook", 1), ("wine_glass", 0.5),
                    ("snack", 0.7), ("open_book", 0.5)]
    CLUTTER_HOSTS = {"CafeTableFactory": (1, 4), "WindowBarFactory": (3, 7), "ReceptionDeskFactory": (6, 10),
                     "WorkstationPodFactory": None, "AboDeskFactory": (3, 6), "ConferenceTableFactory": (2, 5),
                     "BreakTableFactory": (2, 4), "SimpleDeskFactory": (3, 6), "OfficeDeskFactory": (5, 8),
                     "ClinicDeskFactory": (4, 7), "WorkbenchFactory": (7, 11)}   # desks +1: signs of use 5-6 on every floor (r11-r14)   # wh r14: 6 small props per 2 m bench read as bare
    BENCH_CLUTTER = [("tape_gun", 2), ("cardboard_box", 2), ("clipboard", 1), ("paper_stack", 1)]   # no cup / phone: 'a hobby
    # desk' (wh r25, 3 of 3); the open boxes go on at fixed spots (_worktop_props) -- the surface finder fitted 1 of 7                             # warehouse r3: 'bare benches, no open box, tape or labels'
    CLINIC_CLUTTER = [("glove_box", 2), ("sanitizer", 0.8), ("clipboard", 2.5), ("paper_stack", 3), ("pen_cup", 1.5), ("mug", 1.2),
                      ("phone", 1), ("kidney_tray", 1)]
    WORKTOP = [("glove_box", 3), ("sanitizer", 2.5), ("paper_towel", 1.5), ("kidney_tray", 1.5), ("clipboard", 1)]   # no bottle: a
    # green glass bottle on the dental counter read as wine (clinic r21, 2 of 3 calls)
    PACKING = [("open_box", 4), ("kraft_roll", 1.5), ("tape_gun", 1.5), ("shipping_scale", 1.2), ("monitor", 1.0)]   # a parcel being packed on every bench (wh r25)
    LEDGE = [("clipboard", 3), ("sanitizer", 2), ("paper_stack", 2), ("pen_cup", 1.5)]   # the visitor side of a reception counter

    def desk_clutter(self):
        if proc_assets_kit().STYLE.get("desk_clutter") == "off" and self.doc.get("type") in ("office", "meeting-room"):
            return                                              # kit desk_clutter=off: tidy desks (B refs: 'reference desks are tidy')
        """Hands on everything (user 2026-10-16: 'too clean -- leftover snacks, books, pencils, cups'): every desk, pod seat and table
        in an office room gets a handful of small things from CLUTTER (a pod 1.5-2.5 per seat)."""
        if self.doc.get("type") not in ("office", "open-office", "meeting-room", "break-room", "cafe", "clinic-reception", "exam-room",
                                         "dental-room", "physio-room", "pharmacy", "warehouse", "garage", "utility"):   # utility: the
            # sterilisation run's worktop props (floor E3 r15: 'bare counters', steri use 3, 3 of 3); physio: its cabinet run and
            # couches never got props (r31: 'empty counter, bare couch', signs of use 4 in 2 of 2)
            return
        food = [("mug", 3), ("takeaway_cup", 2), ("phone", 0.5)]   # no bottle: 'wine on the staff table' (D3 r21, E3 r17)   # no snack tub ('a crate of folders', H r24); no paper stacks: binders read as
        # 'an office desk, not a lunch table' (floor H r15, 3 of 3)
        # no fruit bowl, snack tubs or can packs: the Infinigen fruit container read as 'a bucket on the staff table' and the tubs/packs as
        # 'retail stock' (floors D3 r11, G r13, H r13, I r9-r12, 3 of 3 each)
        from room_planner import proc_assets as _pa_kit
        for cid, lst in getattr(self, "copies", {}).items():   # every copy of a row is a host (warehouse r8: only the first bench of a
            for k, of in enumerate(lst[1:], 1):                 # row got props, the critic saw 'bare benches' three rounds running)
                self.ids.setdefault(f"{cid}:c{k}", of)
        hosts = {}
        for hid, (o, _) in list(self.ids.items()):
            f = rd._factory(o.name)
            if f in self.CLUTTER_HOSTS and o.name not in hosts:
                hosts[o.name] = hid
        added = 0
        if "flowers" in (_pa_kit.STYLE.get("decor") or []):        # a bud vase on every café table first (floral s3b: 4/10 -- placed
            for name, hid in hosts.items():                          # after the clutter, the vases found no free spot)
                if rd._factory(self.ids[hid][0].name) in ("CafeTableFactory", "WindowBarFactory") and self.rng.random() < 0.35:
                    self.lived_in({"category": "bud_vase", "on": hid}); added += 1   # ~1 table in 3 (cafe r5: 'the same vase on
                    # every table reads as a staged showroom', 3 of 3)
        if "candles" in (_pa_kit.STYLE.get("decor") or []):         # votive candles on most café tables (S10 ref: a candle by every cup; the decor list had 'candles' but nothing placed them)
            for name, hid in hosts.items():
                if rd._factory(self.ids[hid][0].name) in ("CafeTableFactory", "WindowBarFactory") and self.rng.random() < 0.75:
                    self.lived_in({"category": "candle", "on": hid}); added += 1
        for name, hid in hosts.items():
            o = self.ids[hid][0]
            rng_n = self.CLUTTER_HOSTS[rd._factory(o.name)]
            ppt = (_pa_kit.STYLE.get("density") or {}).get("props_per_table")
            if ppt is not None and rd._factory(o.name) in ("CafeTableFactory", "WindowBarFactory"):
                rng_n = (max(1, round(ppt) - 1), round(ppt) + (2 if rd._factory(o.name) == "WindowBarFactory" else 1))
            n = round(len(o.get("seats", [])) * self.rng.uniform(2.5, 4.0)) if rng_n is None else self.rng.randint(*rng_n)   # r5: bench desks bare
            for _ in range(n):
                fac = rd._factory(o.name)
                from room_planner import proc_assets as _pa
                cafe_mix = [m for m in self.CAFE_CLUTTER if m[0] not in _pa.STYLE.get("clutter_exclude", [])] + \
                    [tuple(x) for x in _pa.STYLE.get("table_extra", [])]   # floral: vases; bakery: no wine glasses
                clinic = self.doc.get("type") in ("clinic-reception", "exam-room", "dental-room", "physio-room")
                mix = food if fac == "BreakTableFactory" or (fac == "CafeTableFactory" and self.doc.get("type") == "break-room") else cafe_mix if fac in ("CafeTableFactory", "WindowBarFactory") and \
                    self.doc.get("type") not in ("office", "open-office", "meeting-room", "break-room") \
                    else self.BENCH_CLUTTER if fac == "WorkbenchFactory" \
                    else self.CLINIC_CLUTTER if clinic else self.CLUTTER   # pantry tables: food (r4); cafe: cups, plates; clinic: gloves, forms
                cat = self.rng.choices([m[0] for m in mix], [m[1] for m in mix])[0]
                if cat not in catalog.LIVED_IN:
                    continue
                self.lived_in({"category": cat, "on": hid})
                added += 1
        added += self._worktop_props()
        self.stats["desk_clutter"] = added
        _log(f"desk clutter: {added} items on {len(hosts)} hosts")

    def _worktop_props(self):
        """Clinic cabinet runs: glove boxes, sanitizer, paper towels, trays along the worktop at fixed spacing, off the sink (the surface
        finder only sees the upper cabinets' top over a worktop -- the pantry's problem; clinic r6: 'cabinet counters empty')."""
        n = 0
        # reception: the ledge too (clinic r19: 13 props on the staff-side work surface, all hidden behind the 1.1 m ledge; 3 of 3
        # calls 'the counter holds only two monitors')
        rows = {"MedicalCabinetFactory": ((-0.05, 0.1), 0.94, self.WORKTOP, (0.25, 0.55), True),
                "ReceptionDeskFactory": ((0.26, 0.34), 1.13, self.LEDGE, (0.45, 0.9), False),
                "WorkbenchFactory": ((0.05, 0.15), 0.91, self.PACKING, (0.55, 0.85), False)}
        done = set()                                             # each object once (ids alias objects); every copy of a row is its own
        for hid, (R, _) in list(self.ids.items()):               # object (a bench row: only the first bench got props)
            if rd._factory(R.name) not in rows or R.name in done:
                continue
            done.add(R.name)
            (x0, x1), zt, mix, gap, sink = rows[rd._factory(R.name)]
            L = R.dimensions[1]; y = -L / 2 + 0.1
            while y < L / 2 - 0.2:
                y += self.rng.uniform(*gap)
                if sink and abs(y - (-L / 2 + 0.75)) < 0.35 or y > L / 2 - 0.15:     # the sink sits 0.75 m in from the run's start
                    continue
                cat = self.rng.choices([m[0] for m in mix], [m[1] for m in mix])[0]
                o = self.spawn(_cls(catalog.LIVED_IN[cat]["src"]))
                if o is None:
                    continue
                o.rotation_euler = R.rotation_euler.copy(); o.rotation_euler[2] += self.rng.uniform(-0.4, 0.4)
                bpy.context.view_layer.update()
                f = fr.footprint(o); p = R.matrix_world @ Vector((self.rng.uniform(x0, x1), y / R.scale.y, zt))
                o.location += Vector((p.x - (f[0] + f[1]) / 2, p.y - (f[2] + f[3]) / 2, p.z - f[4]))
                bpy.context.view_layer.update()
                n += 1
        return n

    def _warehouse_plan(self, plan, have=0):
        """Warehouse placement rules, for the first plan and the revision alike (wh r19: the revision re-added two benches 'beside' the
        first and the three stood mid-floor -- layout 7 -> 5). have = benches already placed."""
        nb = [have]
        small = self.doc.get("area_m2", 99) < 20                 # a back stockroom off a shop/café floor, not a packing hall
        def bench(f):                                            # at most 3 benches, on the walls (wh r13/r15: '6-8 benches in a classroom grid')
            if f["category"] != "workbench":
                return f
            k = min(f.get("count", 1), max(0, (0 if small else 3) - nb[0])); nb[0] += k   # a back stockroom has no bench (floor H r9: 'a
                                                                                              # workbench with tools -- a maintenance closet', 3/3)
            # gap 0: the planner's gap_m 2.2 meant 'room to work in front', the realizer reads it as distance from the wall -- the bench
            # row stood 2.2 m out in the floor with racks behind it, the 'bench cluster mid-room' of wh r17-r20
            return {**f, "count": k, "relation": "against_wall", "target": None, "gap_m": 0} if k else None
        fs = [g for g in (bench(f) for f in plan.get("furniture", [])) if g is not None]
        fs = [({**f, "relation": "against_wall", "target": None} if f["category"] in ("pallet", "box_pile") else   # wh r17: 'no pallet-truck lane'
               {**f, "relation": "against_wall", "gap_m": 0, "target": None} if f["category"] in ("storage_rack", "wide_shelf") else f)
              for f in fs]                                       # racks line the walls; the aisle layout owns the middle (wh r10)
        # benches claim their wall before the racks do: placed after them they found no wall and fell back to the room centre (the
        # 'free-standing table' fallback) -- the mid-floor bench cluster of wh r17-r21
        bench0 = next((f["id"] for f in fs if f["category"] == "workbench"), None)
        fs = [({**f, "relation": "in_front_of", "target": bench0, "gap_m": 0.1, "count": min(f.get("count", 1), 2)}
               if f["category"] == "stool" and bench0 else f) for f in fs]   # stools work a bench (floor J r4: a row of 3 mid-hall)
        fs = sorted(fs, key=lambda f: f["category"] != "workbench")
        if self.doc.get("area_m2", 0) >= 120 and not any(f["category"] == "dock_door" for f in fs):   # a dock shutter first, pallets
            # staged in front (floor J r18: 'no loading door, a big stockroom', completeness 6, 3 of 3)
            fs = [{"id": "dock", "category": "dock_door", "relation": "against_wall", "forced": True},
                  {"id": "dock_pallets", "category": "pallet", "relation": "in_front_of", "target": "dock", "gap_m": 1.0, "count": 2,
                   "forced": True}] + fs
        if self.doc.get("area_m2", 0) >= 120:                 # a hall's wall racks are heavy pallet racking: the plan's light wall racks took
            fs = [({**f, "category": "pallet_rack", "forced": True} if f["category"] == "storage_rack" and f.get("relation") == "against_wall"
                   else f) for f in fs]   # every wall and the added pallet row found none ('no pallet racking at height', J r16, 3 of 3)
        n_min = 2 if self.doc.get("area_m2", 99) < 13 else 3   # a 12 m2 room with 3 racks: 'racks jammed, a body-width aisle' (floor G r11)
        if small and sum(f.get("count", 1) for f in fs if f["category"] == "storage_rack") < n_min:   # racks on 2-3 walls (floor H r9)
            fs = fs + [{"id": "rack_fill", "category": "storage_rack", "relation": "against_wall", "gap_m": 0,
                        "count": n_min - sum(f.get("count", 1) for f in fs if f["category"] == "storage_rack")}]
        if small:                                                # a shop/café back stockroom: white wire shelving, not orange pallet racking
            fs = [({**f, "category": "stock_shelf"} if f["category"] in ("storage_rack", "wide_shelf") else f) for f in fs]   # (floor G r11)
        if small:                                                # a back stockroom keeps its floor clear: no pallet or box pile in the
            fs = [f for f in fs if f["category"] not in ("pallet", "box_pile", "stool")]   # door path (floor H r11: layout 5, 3/3); no stool
            # without a bench (floor I r11: 'a lone bar stool'); a cart and a ladder stand on a wall (I r11: 'half empty, no hand truck')
            fs = [({**f, "relation": "against_wall", "target": None} if f["category"] in ("utility_cart", "ladder") else f) for f in fs]
            # (no forced cooler: wedged between the racks it closed the aisle, floor H r40 layout 6, 3 of 3)
            if not any(f["category"] == "utility_cart" for f in fs):   # a cart with the ladder (floor G r16: 'one rack and a step stool')
                fs.append({"id": "cart_x", "category": "utility_cart", "relation": "against_wall"})
            plan = {**plan, "lived_in": [({**x, "category": "dry_goods"} if x.get("category") == "storage_bin" else x)   # no primary-colour
                                         for x in plan.get("lived_in", [])]}   # bins: 'toy blocks' (floor H r18)
            plan = {**plan, "lived_in": [x for x in plan.get("lived_in", []) if x.get("on") != "floor"] +   # no floor stock: loose
                    # cartons 'in the middle of the aisle, cutting the path from the door' (floor I r26, 3 of 3) -- the shelves are full now
                    [{"category": "dry_goods", "on": f["id"], "fill": True} for f in fs if f["category"] == "stock_shelf"]}   # case stacks in the
            from room_planner import proc_assets as _pa_w
            if "cafe" in getattr(_pa_w, "FLOOR_VENUES", ()):     # a café's own stock first: crates, cup tubes, bean bags (floor G r28,
                plan = {**plan, "lived_in": [{"category": "cafe_stock", "on": f["id"], "fill": True} for f in fs   # comp 6, 3 of 3)
                                             if f["category"] == "stock_shelf"] * 2 + [{"category": "cafe_stock", "on": "floor"}] * 3 +
                        [x for x in plan["lived_in"] if x.get("category") != "cardboard_box"]}   # twice, no plain cartons: a fill of 1-4 café
                # items a unit left the cartons to fill the rest, 'generic coloured boxes' (G r29: coherence 6, 2 of 3)
            # corners (floors G/H/I r12-r14: 'half-empty racks, bare floor', completeness 3-5, 9 of 9 calls)
        if small:                                                # its racks are the point: they take the walls first (floor I r3: bench,
            fs = sorted(fs, key=lambda f: f["category"] not in ("storage_rack", "wide_shelf"))   # pallet and boxes left both racks unplaced)
        return {**plan, "furniture": fs}

    def _in_vocab(self, plan):
        """A workplace plan keeps only categories offered for its room type: the planner still named sideboards and vases from memory
        after they left the office vocabulary (office loop r2, 2026-10-16). Homes are unchanged."""
        rt = self.doc.get("type", "")
        if os.environ.get("ROOM_PANTRY_VOCAB") == "1" and str(self.doc.get("id", "")).startswith("break-room") and self.doc.get("area_m2", 0) < 60:
            rt = "break-room"                                    # O3 r3 F2: a floor's pantry is typed 'office' by the archetype, so pantry_run / espresso_machine were off-vocabulary and it was furnished as work desks
            plan = {**plan, "furniture": [({**f_, "category": "break_table"} if f_.get("category") == "cafe_table" else f_) for f_ in plan.get("furniture", [])]}         # a break-room has break tables, not cafe tables: O3 r5 'no seating or table' (both cafe_tables were off-vocabulary)
        if rt not in catalog.WORK_ROOMS:
            return plan
        def ok(c, tab, default):
            return rt in tab.get(c, {}).get("rooms", default)
        drop = [f["category"] for f in plan.get("furniture", []) if not f.get("forced") and not ok(f["category"], catalog.FURNITURE, [])] + \
               [f["category"] for f in plan.get("lived_in", []) if not f.get("forced") and not ok(f["category"], catalog.LIVED_IN, ["home"])]
        lined = [f for f in plan.get("furniture", []) if (f["category"] in SEATS or f["category"] == "armchair")
                 and f["category"] != "bar_stool" and rt in ("office", "open-office", "meeting-room", "cafe")
                 and f.get("relation") in ("row", "against_wall", "corner", "near_window", "beside") and not
                 (f.get("relation") == "beside" and f.get("target") and any(g["id"] == f["target"] and g["category"] in TABLES
                                                                              for g in plan.get("furniture", [])))]
        if lined:                                                # a row of task chairs along a wall reads as a waiting room and
            _log(f"wall-lined seats dropped: {[f['id'] for f in lined]}")   # can't be turned (r5 high-rise c04: 4 chairs at 0 deg)
            plan = {**plan, "furniture": [f for f in plan.get("furniture", []) if f not in lined]}
            self.stats["lined_seats_dropped"] = len(lined)
        if drop:
            _log(f"off-vocabulary for {rt}: {drop}")
            for c in drop:
                self.stats.setdefault("off_vocab", {})[c] = self.stats.get("off_vocab", {}).get(c, 0) + 1
        return {**plan, "furniture": [f for f in plan.get("furniture", []) if f.get("forced") or ok(f["category"], catalog.FURNITURE, [])],
                # forced: an _internal piece the realizer itself added (floor H r20: the café prep station dropped as off-vocabulary)
                "lived_in": [f for f in plan.get("lived_in", []) if f.get("forced") or ok(f["category"], catalog.LIVED_IN, ["home"])]}

    REQUIRED_ITEMS = {"clinic-reception": [("reception_desk", "against_wall"), ("waiting_bench", "against_wall")],
                      "exam-room": [("exam_table", "against_wall"), ("medical_cabinet", "against_wall")],
                      "dental-room": [("dental_chair", "center"), ("medical_cabinet", "against_wall")],
                      "physio-room": [("exam_table", "against_wall"), ("wall_bars", "against_wall"), ("parallel_bars", "center"),
                                      ("exercise_bike", "against_wall"), ("medical_cabinet", "against_wall"),   # sink run (r29: 3 of 3)
                                      ("clinic_desk", "against_wall")],   # a staff desk (r32: 'no therapist desk or chair', 3 of 3)
                      "convenience": [("counter", "near_door"), ("beverage_fridge", "row")],
                      "boutique": [("counter", "near_door"), ("clothing_rack", "against_wall"), ("display_table", "center"), ("fitting_room", "corner")],
                      "pharmacy": [("pharmacy_drawer_wall", "against_wall")],       # (was reception_desk + backbar_shelf: they were force-added next to the kit's counter and drawer wall, S16 r24)
                      "bathroom": [("wc", "against_wall"), ("vanity", "against_wall"), ("shower_glass", "corner")],
                      "bedroom": [("bed", "against_wall")], "kitchen": [("home_kitchen_run", "against_wall")], "dining-room": [("dining_table", "center")],
                      "office": [("office_desk", "against_wall")]}   # P2 r1 FUN-01: no beds, no kitchen run, no study desk   # a home bathroom has its fixtures (P2 r1 FUN-01 x8)

    def _fill_layout(self, plan):
        """Kit room_program[id]["layout"] = layout.json (floor-plan placement, user 2026-10-22): every item is put at its plan position (room_planner/layout_place.py maps the normalised frame onto the room: the entrance
        wall is the wall of the widest door, u runs along it, v into the room), facing as given; `against` snaps its back to that wall; on a collision it nudges up to 0.3 m, else it is dropped.
        stats: layout_placed, layout_dropped {category: n}, layout_error."""
        from room_planner import layout_place as lpl
        import provenance as pv_
        items = lpl.load(plan["layout"])
        walls = {k: ((a.x, a.y), (t.x, t.y), (n.x, n.y), L) for k, (a, t, n, L) in self.walls.items()}
        fr_ = lpl.frame(walls, self.doc.get("doors", []), self.poly)
        placed, dropped = 0, {}
        if fr_ is None:                                          # a room joined to its neighbours only by wide openings (O5 open office) has no door: its plan's entrance wall is the bottom one (floor frame: entrance at y = 0)
            bot_ = sorted((k for k, (a_, t_, n_, L_) in self.walls.items() if n_.y > 0.7), key=lambda k: -self.walls[k][3])
            if bot_:
                fr_ = lpl.frame(walls, [{"wall": bot_[0], "width": 1.0}], self.poly)
                self.stats["layout_frame"] = "bottom_wall_fallback"; _log(f"layout: no door in this room, frame from its bottom wall {bot_[0]}")
        if fr_ is None:
            self.stats["layout_error"] = "no door wall"; _log("layout: NOT RUN, no door wall and no bottom wall to frame it")
            return
        force_mir_ = None
        arcs_ = [(float(k_["u"]), float(k_["v"])) for k_ in (lpl.meta(plan["layout"]).get("keepout") or []) if k_.get("type", "door_arc") == "door_arc" and k_.get("u") is not None and k_.get("v") is not None]
        dws_ = sorted({d_["wall"] for d_ in self.doc.get("doors", []) if d_.get("wall") in walls})
        if arcs_ and len(dws_) >= 2:                             # two doors (a hotel WC, a bedroom with a bath door): the frame's entrance wall is the one that puts the header's door arcs where the doors really are, mirrored or not
            best_ = None
            for wk_ in dws_:
                frc_ = lpl.frame(walls, [d_ for d_ in self.doc.get("doors", []) if d_.get("wall") == wk_], self.poly)
                if frc_ is None:
                    continue
                dp_ = []
                for d_ in self.doc.get("doors", []):
                    if d_.get("wall") in walls:
                        a2_, t2_, n2_, L2_ = self.walls[d_["wall"]]; c2_ = a2_ + t2_ * d_["at_m"]
                        dp_.append((((c2_.x - frc_[0][0]) * frc_[1][0] + (c2_.y - frc_[0][1]) * frc_[1][1]) / frc_[3], ((c2_.x - frc_[0][0]) * frc_[2][0] + (c2_.y - frc_[0][1]) * frc_[2][1]) / frc_[4]))
                for mir_ in (False, True):
                    sc_ = sum(min(abs((1.0 - au_ if mir_ else au_) - du_) + abs(av_ - dv_) for du_, dv_ in dp_) for au_, av_ in arcs_)
                    if best_ is None or sc_ < best_[0] - 1e-6:
                        best_ = (sc_, frc_, mir_, wk_)
            if best_ is not None:
                fr_, force_mir_ = best_[1], best_[2]; self.stats["layout_frame"] = f"arcs:{best_[3]}{'/mirrored' if best_[2] else ''}"
        eu = plan.get("layout_entrance_u")
        if eu is None:                                           # the kit key wins; else the layout.json's own "entrance_u" (Codex writes it per scene)
            eu = lpl.meta(plan["layout"]).get("entrance_u")                         # kit layout_entrance_u: where the PLAN's entrance sits along its entrance wall (0 left .. 1 right); the real door on the other side = the plan seen in a mirror
        mirrored_ = False
        if force_mir_ is not None:
            if force_mir_:
                items = lpl.mirror(items); self.stats["layout_mirrored"] = True; mirrored_ = True
        elif eu is not None:
            ur = lpl.door_u(fr_, walls, self.doc.get("doors", []))
            if ur is not None and (float(eu) - 0.5) * (ur - 0.5) < 0:
                items = lpl.mirror(items); self.stats["layout_mirrored"] = True; mirrored_ = True
        LINE_ = ("fridge", "work_table", "sink", "noodle_boiler", "range", "stock_pot", "stockpot", "gas_range", "hood")      # a ramen cooking line drawn piece by piece: RamenKitchenFactory is all of them
        line_ = [q_ for q_ in items if q_.get("category") in LINE_]
        if line_:
            items = [q_ for q_ in items if q_.get("category") not in LINE_]
            if not any(q_.get("category") == "ramen_kitchen" for q_ in items):
                vs_ = [float(q_["v"]) for q_ in line_]; us_ = [float(q_["u"]) for q_ in line_]
                items = items + [{"category": "ramen_kitchen", "u": round(sum(us_) / len(us_), 3), "v": round((min(vs_) + max(vs_)) / 2, 3), "facing": "right", "against": "left",
                                  "size_m": [round((max(vs_) - min(vs_)) * fr_[4] + 0.9, 2), 1.2], "note": "synthesised from the layout's cooking-line pieces"}]
            _log(f"layout: {len(line_)} cooking-line pieces ({', '.join(sorted({q_['category'] for q_ in line_}))}) folded into ONE ramen_kitchen item")
        for k_ in lpl.meta(plan["layout"]).get("keepout") or []:      # the layout header's door_arc entries {u, v, r}: every door swing the plan wants clear (hotel bathroom + entry doors), mirrored with the items
            try:
                ku_, kv_, kr_ = float(k_["u"]), float(k_["v"]), float(k_.get("r") or k_.get("radius_m") or 0.9)
            except (KeyError, TypeError, ValueError):
                continue
            sw_, me_ = str(k_.get("swing_into") or ""), str(lpl.meta(plan["layout"]).get("room") or "")
            if sw_ and me_ and sw_ != me_:
                continue                                          # this door swings into the NEIGHBOUR room (the hotel bath door opens into the bedroom): nothing to keep clear here
            ang_ = k_.get("angle_deg")                            # the arc's swept sector [a0, a1] degrees in the layout frame (0 = +u, 90 = +v): its bounding box, not the 2r x 2r square round the hinge (H3 WC: 1.8 m box in a 1.77 m room)
            if isinstance(ang_, (list, tuple)) and len(ang_) == 2:
                a0_, a1_ = float(ang_[0]), float(ang_[1]); a1_ += 360.0 if a1_ < a0_ else 0.0
                pts_ = [(0.0, 0.0)] + [(kr_ * math.cos(math.radians(a_)), kr_ * math.sin(math.radians(a_))) for a_ in [a0_ + (a1_ - a0_) * q_ / 8.0 for q_ in range(9)]]
                if mirrored_:
                    pts_ = [(-px_, py_) for px_, py_ in pts_]
                cx_m, cy_m = (1.0 - ku_ if mirrored_ else ku_) * fr_[3], kv_ * fr_[4]
                ws_ = [lpl.to_world(fr_, (cx_m + px_) / fr_[3], (cy_m + py_) / fr_[4]) for px_, py_ in pts_]
                self.obstacles.append((min(w_[0] for w_ in ws_), max(w_[0] for w_ in ws_), min(w_[1] for w_ in ws_), max(w_[1] for w_ in ws_), 0, 0))
            else:
                kx_, ky_ = lpl.to_world(fr_, 1.0 - ku_ if mirrored_ else ku_, kv_)
                self.obstacles.append((kx_ - kr_, kx_ + kr_, ky_ - kr_, ky_ + kr_, 0, 0))
            self.stats["layout_keepouts"] = self.stats.get("layout_keepouts", 0) + 1
        if os.environ.get("ROOM_LAYOUT_KEEP_SEATING") != "1":     # a layout room's seating comes from the layout: chairs / stools an earlier non-layout pass already stood in it (O4 r3: a TaskChair under the desk_bench) are removed first, with their obstacle boxes
            rx0_s, rx1_s, ry0_s, ry1_s = self.room.box; gone_s = 0
            for t_ in list(rd._tops()):
                if t_.type != "MESH" or t_.hide_render or str(t_.get("src", "")).startswith("layout:") or not any(k_ in rd._factory(t_.name) for k_ in ("Chair", "Stool")):
                    continue
                f_s = fr.footprint(t_); cx_s, cy_s = (f_s[0] + f_s[1]) / 2, (f_s[2] + f_s[3]) / 2
                if rx0_s <= cx_s <= rx1_s and ry0_s <= cy_s <= ry1_s and self.room.on_floor(cx_s, cy_s):
                    self.obstacles[:] = [b_ for b_ in self.obstacles if not all(abs(b_[i_] - f_s[i_]) < 0.03 for i_ in range(4))]
                    for c_ in list(t_.children_recursive):
                        bpy.data.objects.remove(c_, do_unlink=True)
                    bpy.data.objects.remove(t_, do_unlink=True); gone_s += 1
            if gone_s:
                self.stats["layout_cleared_seating"] = self.stats.get("layout_cleared_seating", 0) + gone_s; _log(f"layout: cleared {gone_s} planner chairs / stools before placing")
        self._tight_door_zones(0.1, sweep=True)                   # furnish_rooms' 0.9 m clearance round every casing blocked items 2 m from the door (S33 / S31: 'existing' at the door, u .56-.98): the casing + 0.1 m stays, the swing is the keep-out below
        in_ = []
        out_ = []                                                 # header door_arc entries whose swing goes into the neighbour: (u, v) of those doors in this layout's frame
        for k_ in lpl.meta(plan["layout"]).get("keepout") or []:
            try:
                sw_, me_ = str(k_.get("swing_into") or ""), str(lpl.meta(plan["layout"]).get("room") or "")
                if sw_ and me_ and sw_ != me_:
                    out_.append((1.0 - float(k_["u"]) if mirrored_ else float(k_["u"]), float(k_["v"])))
                elif k_.get("type", "door_arc") == "door_arc" and isinstance(k_.get("angle_deg"), (list, tuple)):
                    in_.append((1.0 - float(k_["u"]) if mirrored_ else float(k_["u"]), float(k_["v"])))              # this door swings INTO the room and the plan drew its sector: that sector is the true swing
            except (KeyError, TypeError, ValueError):
                pass
        for dr in self.doc.get("doors", []):                      # door keep-out: the leaf's swing and a walk-in lane stay clear (a chair or stool in the doorway is the first layout failure)
            if dr.get("wall") not in self.walls:
                continue
            a_, t_, n_, L_ = self.walls[dr["wall"]]
            w_ = dr.get("width", 1.0); c_ = a_ + t_ * dr["at_m"]
            du_, dv_ = ((c_.x - fr_[0][0]) * fr_[1][0] + (c_.y - fr_[0][1]) * fr_[1][1]) / fr_[3], ((c_.x - fr_[0][0]) * fr_[2][0] + (c_.y - fr_[0][1]) * fr_[2][1]) / fr_[4]
            if any(abs(du_ - ku2_) < 0.3 and abs(dv_ - kv2_) < 0.25 for ku2_, kv2_ in in_):
                continue                                          # the header's door_arc sector (added above) is this door's swing: no second, bigger doc-door box (H3 WC: 1.48 x 1.3 m on top of the 0.9 m sector left a 0.37 m band); the casing + 0.1 m stays
            swings_out = any(abs(du_ - ku2_) < 0.3 and abs(dv_ - kv2_) < 0.25 for ku2_, kv2_ in out_)          # this door opens away from this room: only the casing + a lane
            pts = [c_ + t_ * sg * (w_ / 2 + 0.1) + n_ * dd for sg in (1, -1) for dd in (0.0, 0.25 if swings_out else min(w_, 1.0) + 0.3)]
            self.obstacles.append((min(q.x for q in pts), max(q.x for q in pts), min(q.y for q in pts), max(q.y for q in pts), 0, 0))
        CAT_MAP = {"banquette_row": "banquette", "window_bar": "counter", "coffee_bar": "counter", "floor_lamp": "standing_lamp",
                   "office_chair": "desk_chair", "planter_divider": "floor_plant", "toilet": "wc", "washbasin": "vanity", "wardrobe": "oak_wardrobe", "shower": "shower_glass", "curtains": "curtain", "storage_cabinet": "oak_credenza", "tv_screen": "wall_display", "wire_stool": "wire_stool"}      # planner zone categories -> the plain object (a zone is built by the planner's zone code, not here)
        TABLES, SEATS = ("cafe_table", "dining_table", "break_table", "counter"), ("cafe_chair", "dining_chair", "bar_stool", "armchair")
        area_ = lambda c_: (lambda z_: z_[0] * z_[1])(catalog.FURNITURE.get(CAT_MAP.get(c_, c_), {}).get("size", [0.5, 0.5, 0.8]))
        order = sorted(range(len(items)), key=lambda k_: (0 if items[k_].get("category") in ("rug", "round_rug") else 2 if items[k_].get("category") in SEATS else 1, -area_(items[k_].get("category"))))   # rugs, then the big pieces, then seats
        platforms = []                                           # raised_platform footprints (x0, x1, y0, y1, height): a platform is a floor, not an obstacle; pieces standing on it are lifted by its height
        labels, why_, anchors = {}, [], []                       # obstacle -> category; drop reasons; placed tables / counters (target centre, shift, target box)
        for b_ in list(self.obstacles)[-len(self.doc.get("doors", [])):]:
            labels[b_] = "door_keepout"
        cols = []                                                # structural columns: items with category "column" (u, v, size_m) or the layout header's architecture.structural_columns; obstacles + gaps in a spanned wall, never spawned
        for e_ in items:
            if e_.get("category") == "column":
                cols.append((float(e_["u"]), float(e_["v"]), tuple(e_.get("size_m") or (0.5, 0.5))))
        if not cols:
            for c_ in (lpl.meta(plan["layout"]).get("architecture") or {}).get("structural_columns", []):
                cols.append((float(c_["u"]), float(c_["v"]), tuple(c_.get("size_m") or (0.5, 0.5))))
        col_xy, col_boxes = [], []
        for cu_, cv_, (cw_, cd_) in cols:
            cx_w, cy_w = lpl.to_world(fr_, cu_, cv_)
            col_xy.append((cx_w, cy_w, cw_, cd_))
            cb_ = (cx_w - cw_ / 2, cx_w + cw_ / 2, cy_w - cd_ / 2, cy_w + cd_ / 2, self.room.z, self.room.z + 3.0)
            self.obstacles.append(cb_); col_boxes.append(cb_)
        items = [e_ for e_ in items if e_.get("category") != "column"]
        order = sorted(range(len(items)), key=lambda k_: (0 if items[k_].get("category") in ("rug", "round_rug") else 2 if items[k_].get("category") in SEATS else 1, -area_(items[k_].get("category"))))
        for cb_ in col_boxes:
            labels[cb_] = "column"
        wall_fronts = {}                                         # wall id -> [(s0, s1, depth)]: a spanned LP wall's face is the wall line for items placed against that wall afterwards
        todo = []                                                # layout item "span": "full" | <metres> with "against": the item stretches along its wall (LP grid: more cell columns) over each free run
        for k_ in order:
            e = items[k_]
            sp_ = e.get("span")
            kw = lpl.wall_for(walls, fr_, e.get("against")) if (sp_ and e.get("category") == "lp_grid_wall") else None
            if kw is None:
                todo.append(e); continue
            Lw = walls[kw][3]
            blocked = sorted([(b[0] - 0.15, b[1] + 0.15) for wd in self.doc.get("walls", []) if wd["id"] == kw for b in wd.get("blocked", [])] +
                             [((cx_w - walls[kw][0][0]) * walls[kw][1][0] + (cy_w - walls[kw][0][1]) * walls[kw][1][1] - cw_ / 2 - 0.05, (cx_w - walls[kw][0][0]) * walls[kw][1][0] + (cy_w - walls[kw][0][1]) * walls[kw][1][1] + cw_ / 2 + 0.05)
                              for cx_w, cy_w, cw_, cd_ in col_xy if abs((cx_w - walls[kw][0][0]) * walls[kw][2][0] + (cy_w - walls[kw][0][1]) * walls[kw][2][1]) < cd_ / 2 + 0.7])      # a column on the wall line = a gap
            (wax, way), (wtx, wty), (wnx, wny), _wl = walls[kw]                      # every obstacle (door zones, pilasters, columns ...) standing in the 0.4 m strip along this wall is a gap too
            for ob_ in self.obstacles:
                cs_ = [((x_ - wax) * wtx + (y_ - way) * wty, (x_ - wax) * wnx + (y_ - way) * wny) for x_ in (ob_[0], ob_[1]) for y_ in (ob_[2], ob_[3])]
                if min(c_[1] for c_ in cs_) < 0.4 and max(c_[1] for c_ in cs_) > -0.1 and (ob_[5] - ob_[4] > 0.3 or ob_[5] == ob_[4]):          # tall things, and the zero-height door keep-out zones
                    blocked.append((min(c_[0] for c_ in cs_) - 0.05, max(c_[0] for c_ in cs_) + 0.05))
            blocked.sort()
            runs, cur = [], 0.1
            for b0, b1 in blocked:                               # free intervals between doors / windows
                if b0 - cur >= 1.4:
                    runs.append((cur, b0))
                cur = max(cur, b1)
            if Lw - 0.1 - cur >= 1.4:
                runs.append((cur, Lw - 0.1))
            runs = [(a_, min(b_, Lw - 0.1)) for a_, b_ in runs if min(b_, Lw - 0.1) - a_ >= 1.4]          # a free run never leaves the wall: an obstacle whose wall-line coordinate lay far past the wall's end made a 14.5 m 'run' on an 8.7 m wall (S34 r14: 41 columns)
            if sp_ != "full":                                    # a given length: one module of that many metres on the longest free run
                runs = [max(runs, key=lambda r_: r_[1] - r_[0])] if runs else []
                if runs:
                    a0_, b0_ = runs[0]; ln_ = min(float(sp_), b0_ - a0_); runs = [(a0_ + (b0_ - a0_ - ln_) / 2, a0_ + (b0_ - a0_ - ln_) / 2 + ln_)]
            for a0_, b0_ in runs:
                todo.append({**e, "_s": (a0_ + b0_) / 2, "_ncols": max(4, int((b0_ - a0_ - 0.1) / 0.35))})
            if not runs:
                todo.append(e)
        todo.sort(key=lambda e_: -1 if e_.get("category") in ("keepout", "door_arc") else 0 if e_.get("_ncols") else 1 if e_.get("category") == "raised_platform" else 3 if (e_.get("category") in catalog.LIVED_IN and e_.get("category") not in catalog.FURNITURE) else 2)        # spanned LP walls first (their face becomes the wall line), then platforms (in front of them), then the rest
        arcs_all_ = []                                           # (box, swings_into_this_room): the header door arcs as half-disc boxes (H3 r13 / r17)
        if os.environ.get("ROOM_BATH_COMPACT") == "1" and self.doc.get("area_m2", 9) < 6:
            mt_ = lpl.meta(plan["layout"])
            for k_ in (mt_.get("keepout") or []):
                if k_.get("type") != "door_arc" or k_.get("u") is None:
                    continue
                hx_, hy_ = lpl.to_world(fr_, float(k_["u"]), float(k_["v"]))
                a0_, a1_ = ((math.pi, 2 * math.pi) if float(k_.get("v", 0)) > 0.5 else (0.0, math.pi)); r_ = 0.85 * float(k_.get("r") or 0.9)
                pts_ = [(hx_ + r_ * (math.cos(a_) * fr_[1][0] + math.sin(a_) * fr_[2][0]), hy_ + r_ * (math.cos(a_) * fr_[1][1] + math.sin(a_) * fr_[2][1])) for a_ in [a0_ + (a1_ - a0_) * q_ / 6 for q_ in range(7)]] + [(hx_, hy_)]
                arcs_all_.append(((min(p_[0] for p_ in pts_), max(p_[0] for p_ in pts_), min(p_[1] for p_ in pts_), max(p_[1] for p_ in pts_), 0, 0), str(k_.get("swing_into", "")) == str(mt_.get("room", ""))))
        if os.environ.get("ROOM_BATH_COMPACT") == "1" and self.doc.get("area_m2", 9) < 6 and any(e_.get("category") == "shower" for e_ in todo):      # H3 r18 FUN-01: the two door half-discs squeezed the shower out -> in a compact wet room the SHOWER goes first, in the corner farthest from both door hinges (0.8 x 0.8), then the keepouts, then wc / basin
            mt0_ = lpl.meta(plan["layout"]); hing_ = [lpl.to_world(fr_, float(k_["u"]), float(k_["v"])) for k_ in (mt0_.get("keepout") or []) if k_.get("type") == "door_arc" and k_.get("u") is not None]
            sh_o, sh_f = self._make("shower_glass")
            if sh_o is not None:
                bpy.context.view_layer.update(); d0_ = sh_o.dimensions; k0_ = min(1.0, 0.8 / max(d0_[0], 1e-3)), min(1.0, 0.8 / max(d0_[1], 1e-3))
                sh_o.scale = (sh_o.scale[0] * k0_[0], sh_o.scale[1] * k0_[1], sh_o.scale[2]); bpy.context.view_layer.update()
                rx0_, rx1_, ry0_, ry1_ = self.room.box; ok_s = False
                cand_ = [(rx0_ + 0.4 + i_ * 0.1, ry0_ + 0.4 + j_ * 0.1) for i_ in range(int(max(rx1_ - rx0_ - 0.8, 0) / 0.1) + 1) for j_ in range(int(max(ry1_ - ry0_ - 0.8, 0) / 0.1) + 1)]
                near_ = lambda c_: min([math.hypot(c_[0] - h_[0], c_[1] - h_[1]) for h_ in hing_] or [9.0])
                wall_ = lambda c_: min(c_[0] - rx0_, rx1_ - c_[0], c_[1] - ry0_, ry1_ - c_[1])
                cand_.sort(key=lambda c_: (round(wall_(c_) / 0.15), -near_(c_)))          # against a wall first (nearest 15 cm band), farthest from the hinges within a band
                for px_, py_ in cand_:
                    yaw_ = math.atan2((ry0_ + ry1_) / 2 - py_, (rx0_ + rx1_) / 2 - px_)
                    for yw_ in (0.0, math.pi / 2, math.pi, -math.pi / 2, yaw_):
                        tmp_obs_ = list(self.obstacles) + [b_ for b_, _sw in arcs_all_]          # the SHOWER keeps clear of every door arc (the tray must never be crossed) ...
                        if fr._place(sh_o, px_, py_, yw_, self.room, tmp_obs_, sh_f):
                            ok_s = True; self.obstacles.append(tmp_obs_[-1]); break
                    if ok_s:
                        break
                _log(f"shower_first: room {self.doc.get('id')} area {self.doc.get('area_m2')} hinges {[(round(h_[0], 2), round(h_[1], 2)) for h_ in hing_]} box {[round(v_, 2) for v_ in self.room.box]} placed {ok_s}")
                if ok_s:
                    self.ids["shower_first"] = (sh_o, sh_f); self.stats["furniture_added"] += 1; placed += 1; self.stats["shower_first"] = self.stats.get("shower_first", 0) + 1
                    todo = [e_ for e_ in todo if e_.get("category") != "shower"]
                else:
                    bpy.data.objects.remove(sh_o, do_unlink=True)
        for kb_, sw_ in arcs_all_:                               # ... but a wc / basin only keeps clear of the arc that swings into this room: two half-discs left no wall in a 4 m2 room (H3 r19)
            if sw_:
                self.obstacles.append(kb_); labels[kb_] = "door_keepout"; self.stats["layout_keepouts"] = self.stats.get("layout_keepouts", 0) + 1
        gone_desks_ = []                                         # layout desks that could not be placed: their chair and TV follow them out
        for e in todo:
            cat = e.get("category")
            if cat in ("keepout", "door_arc"):                    # a door swing the plan wants clear (hotel bathroom / entry doors): u, v = the hinge-side centre, radius_m (default 0.9) -> a zero-height box nothing may stand in
                kx_, ky_ = lpl.to_world(fr_, float(e["u"]), float(e["v"])); kr_ = float(e.get("radius_m") or (e.get("size_m") or [1.8])[0] / 2)
                kb_ = (kx_ - kr_, kx_ + kr_, ky_ - kr_, ky_ + kr_, 0, 0); self.obstacles.append(kb_); labels[kb_] = "door_keepout"
                self.stats["layout_keepouts"] = self.stats.get("layout_keepouts", 0) + 1
                continue
            dbg_ = None
            note_ = str(e.get("note", "")).lower()
            if cat in ("curtain", "curtains"):                    # a layout curtain is the window-curtain pass (it hangs on the window spans), not a floor item
                self._want_curtains = True; placed += 1
                continue
            if cat == "sideboard" and any(w_ in note_ for w_ in ("cooler", "refrigerator", "fridge")):
                cat = "beverage_fridge"                           # Codex only has sideboard for a tall cabinet: a note saying cooler / fridge makes it the fridge
            if cat in catalog.LIVED_IN and cat not in catalog.FURNITURE:        # a table-top item in the layout (pastry_case, register, ...): put on its counter instead of the floor
                xl_, yl_ = lpl.to_world(fr_, float(e["u"]), float(e["v"]))
                host_ = e.get("on")
                if not host_:                                     # the nearest PLACED layout item of a kind this item may stand on (table_lamp -> a nightstand / desk), else the nearest table / counter
                    cand_ = [(l_, fr.footprint(self.ids[l_][0])) for l_, c_ in getattr(self, "layout_items", []) if l_ in self.ids and c_ in catalog.LIVED_IN[cat].get("on", [])]
                    if cand_:
                        host_ = min(cand_, key=lambda lf_: ((lf_[1][0] + lf_[1][1]) / 2 - xl_) ** 2 + ((lf_[1][2] + lf_[1][3]) / 2 - yl_) ** 2)[0]
                    elif anchors:
                        host_ = min(anchors, key=lambda a_: (a_["tx"] - xl_) ** 2 + (a_["ty"] - yl_) ** 2)["id"]       # a table-top item goes on the nearest table / counter (flower vase on its table), or the explicit "on"
                if host_ in self.ids:
                    with pv_.tag("layout:" + str(e.get("id") or cat)):
                        self._layout_lived({"category": cat, "on": host_})
                    placed += 1
                else:
                    dropped[cat] = dropped.get(cat, 0) + 1; why_.append({"category": cat, "u": e.get("u"), "v": e.get("v"), "reason": "no_host"})
                continue
            sz_ = e.get("size_m")                                # layout size_m = [length along the wall, depth]: honoured for platforms, island counters, counters, banquettes
            mcat = (proc_assets_kit().STYLE.get("layout_cat_map") or {}).get(cat) or CAT_MAP.get(cat, cat)         # kit layout_cat_map {"tv_stand": "wall_display"}: this reference's category -> a prop
            if cat == "counter" and ((sz_ and float(sz_[0]) >= 3.0 and len(sz_) > 1 and float(sz_[1]) >= 1.2) or "curved_island" in str(e.get("note", ""))):       # a WIDE long counter = the island; a long thin one (a ramen bar 5.6 x 0.7) stays a counter
                mcat = "island_counter"                           # a long / curved island is its own prop (stadium shape, LP sleeve front, pastry case + machines on top)
            note_ = str(e.get("note", "")).lower()
            if cat == "counter" and "reception" in note_:        # office floors: the plan's reception / cafe counters
                mcat = "reception_desk"
            elif cat == "counter" and ("cafe_island" in note_ or "white island" in note_ or "white_island" in note_):
                mcat = "white_island"
            LIN_ = ("counter", "desk_bench", "banquette", "banquette_row", "break_table", "dining_table", "backbar", "backbar_shelf", "bookshelf", "island_counter", "reception_desk", "white_island", "oak_wardrobe")
            if sz_ and len(sz_) > 0 and (cat in LIN_ or mcat in LIN_) and mcat != "raised_platform":        # shrink-to-fit: a linear item longer than the room along its length axis gets the room span - 0.2 m (at least 60 % of the request) instead of being dropped 'off_floor' (O4 r3: counters 1.7 normalised units long in a 1.0 room)
                _O2, _R2, _n2, W2_, D2_, _w2 = fr_
                ax_ = D2_ if str(e.get("facing", "front")) in ("left", "right") else W2_
                l_ = float(sz_[0]); room_l = ax_ - 0.2
                if l_ > room_l:
                    nl_ = round(max(room_l, 0.6 * l_), 2)
                    sz_ = [nl_] + list(sz_[1:]); e = {**e, "size_m": sz_}; self.stats["layout_shrunk"] = self.stats.get("layout_shrunk", 0) + 1
                    _log(f"layout: shrunk {cat} {l_:.2f}->{nl_:.2f} (room span {ax_:.2f})")
            if mcat == "raised_platform" and sz_ and len(sz_) > 1:       # a platform whose footprint would cross a wall is shifted back inside (shrunk when the room is smaller than it), not dropped: S33 r8 6 x 4.2 m at u .79 in a 9.8 m room
                _O, _R, _n, W_, D_, _w = fr_
                fdx_, fdy_ = lpl.direction(fr_, e.get("facing", "front"))                 # the platform's length runs perpendicular to its front: facing left / right puts the 6 m along v (S33 r9: 54 / 54 candidates off the floor)
                along_u = abs(-fdy_ * _R[0] + fdx_ * _R[1]) > 0.7
                lim_l, lim_d = ((W_, D_) if along_u else (D_, W_))
                hl_, hd_ = min(float(sz_[0]) / 2, (lim_l - 0.2) / 2), min(float(sz_[1]) / 2, (lim_d - 0.2) / 2)
                hu_, hv_ = (hl_, hd_) if along_u else (hd_, hl_)
                ul_, vl_ = (hu_ + 0.1) / W_, (hv_ + 0.1) / D_
                e = {**e, "u": min(max(float(e["u"]), ul_), 1 - ul_), "v": min(max(float(e["v"]), vl_), 1 - vl_), "size_m": [2 * hl_, 2 * hd_]}
                sz_ = e["size_m"]
            if cat == "break_table" and not sz_:                  # no size from the plan: a communal table is as long as the row of seats round it (S34: six chairs a side beside a 1.2 m table) and turned along that row
                seat_ = [lpl.to_world(fr_, float(q_["u"]), float(q_["v"])) for q_ in items if q_.get("category") in ("cafe_chair", "dining_chair", "break_chair", "bar_stool")]
                tx_, ty_ = lpl.to_world(fr_, float(e["u"]), float(e["v"]))
                near_ = [p_ for p_ in seat_ if (p_[0] - tx_) ** 2 + (p_[1] - ty_) ** 2 < 3.5 ** 2]
                if len(near_) >= 4:
                    ru_ = [((p_[0] - fr_[0][0]) * fr_[1][0] + (p_[1] - fr_[0][1]) * fr_[1][1]) for p_ in near_]; rv_ = [((p_[0] - fr_[0][0]) * fr_[2][0] + (p_[1] - fr_[0][1]) * fr_[2][1]) for p_ in near_]
                    su_, sv_ = max(ru_) - min(ru_), max(rv_) - min(rv_)
                    long_, cross_ = max(su_, sv_), min(su_, sv_)
                    sz_ = [round(long_ + 0.55, 2), round(min(max(cross_ - 0.8, 0.8), 1.4), 2)]
                    e = {**e, "facing": "right" if sv_ >= su_ else "front"}                  # the length axis is perpendicular to the table's front
            restore = []
            try:
                from room_planner import proc_lp as _pl
                kst = proc_assets_kit().STYLE
                if e.get("_ncols"):
                    _pl.LpGridWallFactory.NC = int(e["_ncols"]); restore.append(lambda: setattr(_pl.LpGridWallFactory, "NC", 14))
                if mcat == "break_table" and sz_ and len(sz_) > 1:
                    from room_planner import proc_assets as _pa_t
                    old_d = _pa_t.BreakTableFactory.DIMS; _pa_t.BreakTableFactory.DIMS = (float(sz_[0]), float(sz_[1])); restore.append(lambda a_=old_d: setattr(_pa_t.BreakTableFactory, "DIMS", a_))
                if mcat == "backbar_shelf":                       # a 'full-height' / 'floor-standing' shelf (S31 stillroom_entry_shelf) is a floor-to-2.2 m unit, not the wall-hung bar-back that reads as a box on rods when it stands free
                    nt_ = str(e.get("note", "")).lower()
                    if "full-height" in nt_ or "full height" in nt_ or ("floor-standing" in nt_ and "not floor-standing" not in nt_):
                        from room_planner import proc_assets as _pa_b
                        old_f = _pa_b.BackBarShelfFactory.FULL; _pa_b.BackBarShelfFactory.FULL = True; restore.append(lambda a_=old_f: setattr(_pa_b.BackBarShelfFactory, "FULL", a_))
                if mcat == "open_chiller" and sz_:
                    from room_planner import proc_office as _po_c
                    old_c = _po_c.OpenChillerFactory.LEN; _po_c.OpenChillerFactory.LEN = float(sz_[0]); restore.append(lambda a_=old_c: setattr(_po_c.OpenChillerFactory, "LEN", a_))
                if mcat == "ramen_kitchen" and sz_:
                    old_k = _pl.RamenKitchenFactory.LEN; _pl.RamenKitchenFactory.LEN = float(sz_[0]); restore.append(lambda a_=old_k: setattr(_pl.RamenKitchenFactory, "LEN", a_))
                if mcat == "oak_wardrobe" and sz_:
                    from room_planner import proc_home as _ph_
                    old_l = _ph_.OakWardrobeFactory.LEN; _ph_.OakWardrobeFactory.LEN = max(0.6, float(sz_[0])); restore.append(lambda a_=old_l: setattr(_ph_.OakWardrobeFactory, "LEN", a_))
                if mcat == "desk_bench":                         # seats = desks per side (a bench of size_m[0] m at 1.2 m a desk when not given); chairs follow the placement (_pod_chairs)
                    from room_planner import proc_office as _po
                    old_n = _po.DeskBenchFactory.N
                    _po.DeskBenchFactory.N = max(1, int(e.get("seats") or round(float(sz_[0]) / 1.2) if sz_ else old_n)); restore.append(lambda a_=old_n: setattr(_po.DeskBenchFactory, "N", a_))
                if sz_ and mcat in ("raised_platform", "island_counter", "white_island"):
                    from room_planner import proc_office as _po2
                    fac_ = {"raised_platform": _pl.RaisedPlatformFactory, "island_counter": _pl.IslandCounterFactory, "white_island": _po2.WhiteIslandFactory}[mcat]
                    o_pl, o_pd = fac_.PL, fac_.PD
                    fac_.PL, fac_.PD = float(sz_[0]), float(sz_[1]) if len(sz_) > 1 else fac_.PD
                    restore.append(lambda f_=fac_, a_=o_pl, b_=o_pd: (setattr(f_, "PL", a_), setattr(f_, "PD", b_)))
                if sz_ and mcat in ("counter", "banquette"):
                    key_ = "counter_len_m" if mcat == "counter" else "banquette_len_m"
                    old_ = kst.get(key_); kst[key_] = [float(sz_[0]), float(sz_[0])]
                    restore.append(lambda k_=key_, v_=old_: kst.pop(k_, None) if v_ is None else kst.__setitem__(k_, v_))
                try:
                    o, front = self._make(mcat)
                finally:
                    for rf_ in restore:
                        rf_()
            except Exception as ex:                              # noqa: BLE001 -- an unknown category is dropped, not fatal
                _log(f"layout {cat}: {ex!r}"[:120]); o = None
            if o is None:
                dropped[cat] = dropped.get(cat, 0) + 1; why_.append({"category": cat, "u": e.get("u"), "v": e.get("v"), "reason": "no_asset"})
                continue
            if os.environ.get("ROOM_TV_AVOID_WINDOW") == "1" and cat in ("tv_stand", "tv_screen") and mcat in ("wall_display", "tv_stand"):      # H2 r18: a 1.47 m TV fits no window-free stretch of a 5.3 m wall with a 1 m window -> a 50-inch (1.15 m) TV, with a 0.3 m window margin
                bpy.context.view_layer.update()
                if o.dimensions[1] > 1.15:
                    k_ = 1.15 / o.dimensions[1]; o.scale = (o.scale[0] * k_, o.scale[1] * k_, o.scale[2] * k_); bpy.context.view_layer.update()
            if os.environ.get("ROOM_BATH_COMPACT") == "1" and sz_ and mcat in ("shower_glass", "wc", "wash_basin", "vanity") and self.doc.get("area_m2", 9) < 6:      # H3 r12 FUN-01: a 1.8 x 2.3 m wc + shower room: the 0.96 m shower took the room, no wc / basin fitted -> every piece at (at most) its reference size
                bpy.context.view_layer.update(); d_ = o.dimensions
                if mcat == "shower_glass":
                    kx_, ky_ = min(1.0, 0.8 / max(d_[0], 1e-3)), min(1.0, 0.8 / max(d_[1], 1e-3))
                elif mcat in ("wash_basin", "vanity"):
                    kx_, ky_ = min(1.0, max(float(sz_[1]) if len(sz_) > 1 else 0.4, 0.4) / max(d_[0], 1e-3)), min(1.0, max(float(sz_[0]), 0.5) / max(d_[1], 1e-3))
                else:
                    kx_, ky_ = min(1.0, max(float(sz_[1]) if len(sz_) > 1 else 0.5, 0.5) / max(d_[0], 1e-3)), min(1.0, max(float(sz_[0]), 0.4) / max(d_[1], 1e-3))
                o.scale = (o.scale[0] * kx_, o.scale[1] * ky_, o.scale[2]); bpy.context.view_layer.update()
            x, y = lpl.to_world(fr_, float(e["u"]), float(e["v"]))
            if cat in SEATS:                                     # a seat follows its table / counter: the anchor's nudge shifts the whole set
                near = [a_ for a_ in anchors if a_["box"][0] - 0.9 <= x <= a_["box"][1] + 0.9 and a_["box"][2] - 0.9 <= y <= a_["box"][3] + 0.9]
                if near:
                    a_ = min(near, key=lambda a: (a["tx"] - x) ** 2 + (a["ty"] - y) ** 2)
                    x, y = x + a_["dx"], y + a_["dy"]
            dx, dy = lpl.direction(fr_, e.get("facing", "front"))
            yaw = math.atan2(dy, dx)
            base, tang, wall_n, side_wall = (x, y), None, None, None
            rzh_ = yaw - math.atan2(front[1], front[0])                               # half extents of the rotated footprint
            pts_h = [(Matrix.Rotation(rzh_, 3, "Z") @ Matrix.Diagonal(o.scale)) @ p_ for p_ in fr._local_points(o)]
            hx_h, hy_h = (max(p_.x for p_ in pts_h) - min(p_.x for p_ in pts_h)) / 2, (max(p_.y for p_ in pts_h) - min(p_.y for p_ in pts_h)) / 2
            if cat in SEATS and anchors:                          # a stool the plan drew overlapping its counter (centre-to-centre placements): stand it at the counter's customer edge, on the side its front points away from (S32 r8: the stools were pushed 0.8 m out)
                for a_ in anchors:
                    if a_["id"] not in self.ids:
                        continue
                    fp_ = fr.footprint(self.ids[a_["id"]][0])
                    if fp_[0] - hx_h < x < fp_[1] + hx_h and fp_[2] - hy_h < y < fp_[3] + hy_h:
                        if abs(dx) >= abs(dy):
                            base = ((fp_[1] + hx_h + 0.06) if dx < 0 else (fp_[0] - hx_h - 0.06), min(max(y, fp_[2] + hy_h), fp_[3] - hy_h))
                        else:
                            base = (min(max(x, fp_[0] + hx_h), fp_[1] - hx_h), (fp_[3] + hy_h + 0.06) if dy < 0 else (fp_[2] - hy_h - 0.06))
                        break
            side = e.get("against")
            hid_ = self.layout_cat_ids.get(e.get("against_cat")) if (e.get("against_cat") and getattr(self, "layout_cat_ids", None)) else None
            if hid_ in self.ids:                                  # "against_cat": <category>: the back of this item touches the FRONT face of the first placed item of that category (a counter against the kitchen block)
                ho_, hfr_ = self.ids[hid_]
                hy_ = ho_.rotation_euler.z + math.atan2(hfr_[1], hfr_[0])
                cx_h, cy_h = math.cos(hy_), math.sin(hy_)
                hn_ = (math.copysign(1.0, cx_h), 0.0) if abs(cx_h) >= abs(cy_h) else (0.0, math.copysign(1.0, cy_h))        # the host's front direction, snapped to an axis
                hp_ = fr.footprint(ho_)
                face_ = (hp_[1] if hn_[0] > 0 else hp_[0]) if hn_[0] else (hp_[3] if hn_[1] > 0 else hp_[2])
                rz_ = yaw - math.atan2(front[1], front[0])
                R3_ = Matrix.Rotation(rz_, 3, "Z") @ Matrix.Diagonal(o.scale)
                pts_ = [R3_ @ p_ for p_ in fr._local_points(o)]
                cx2_, cy2_ = (min(p_.x for p_ in pts_) + max(p_.x for p_ in pts_)) / 2, (min(p_.y for p_ in pts_) + max(p_.y for p_ in pts_)) / 2
                h2_ = max(abs((p_.x - cx2_) * hn_[0] + (p_.y - cy2_) * hn_[1]) for p_ in pts_)         # the item's half depth along that direction
                if hn_[0]:
                    base = (face_ + hn_[0] * (h2_ + 0.08), y); tang = (0.0, 1.0)         # 0.08: the obstacle test keeps a 5 cm margin round every piece
                else:
                    base = (x, face_ + hn_[1] * (h2_ + 0.08)); tang = (1.0, 0.0)
                wall_n = hn_
            if side in ("front", "back", "left", "right"):
                k = lpl.wall_for(walls, fr_, side)
                if k is not None:
                    (ax, ay), (tx, ty), (nx, ny), L = walls[k]
                    rz = yaw - math.atan2(front[1], front[0])
                    R3 = Matrix.Rotation(rz, 3, "Z") @ Matrix.Diagonal(o.scale)
                    pts = [R3 @ p for p in fr._local_points(o)]
                    cx_, cy_ = (min(p.x for p in pts) + max(p.x for p in pts)) / 2, (min(p.y for p in pts) + max(p.y for p in pts)) / 2
                    hl_ = max(abs((p.x - cx_) * tx + (p.y - cy_) * ty) for p in pts)             # half length along the wall: a 3 m bench must not slide past the room's end
                    s_ = min(max((x - ax) * tx + (y - ay) * ty, hl_ + 0.05), max(L - hl_ - 0.05, hl_ + 0.05))
                    if e.get("_s") is not None:
                        s_ = min(max(float(e["_s"]), hl_ + 0.05), max(L - hl_ - 0.05, hl_ + 0.05))                         # a spanned item sits on the centre of its free run (kept on the wall: a run longer than the wall put the item off the floor)
                    h = max((p.x - cx_) * nx + (p.y - cy_) * ny for p in pts)            # the footprint's half depth towards the wall
                    off_ = max((d_ for a0_, a1_, d_ in wall_fronts.get(k, []) if a0_ - 0.1 <= s_ <= a1_ + 0.1), default=0.0)        # in front of a spanned LP wall: stand on its face, not the bare wall
                    base, tang = (ax + tx * s_ + nx * (h + 0.03 + off_), ay + ty * s_ + ny * (h + 0.03 + off_)), (tx, ty)
                    dbg_ = {"wall": k, "wall_len": round(L, 2), "s": round(s_, 2), "half_len": round(hl_, 2), "run_s": e.get("_s"), "ncols": e.get("_ncols"), "dims": [round(v_, 2) for v_ in o.dimensions]}
                    side_wall = k
                    wall_n = (nx, ny)
            big = area_(cat) >= 1.2                              # a counter / kitchen / sideboard may slide up to 0.6 m, small pieces 0.3 m
            cands = [base]
            rx0_, rx1_, ry0_, ry1_ = self.room.box                 # a piece a few cm over a wall (H3 WC toilet, an armchair 5 cm into the wall): the same spot moved just inside the room is the first alternative
            cl_ = (min(max(base[0], rx0_ + hx_h + 0.06), rx1_ - hx_h - 0.06), min(max(base[1], ry0_ + hy_h + 0.06), ry1_ - hy_h - 0.06))
            if abs(cl_[0] - base[0]) + abs(cl_[1] - base[1]) > 1e-3 and abs(cl_[0] - base[0]) < 0.35 and abs(cl_[1] - base[1]) < 0.35:
                cands.append(cl_)
            for r_ in ((0.1, 0.2, 0.3, 0.4, 0.5, 0.6) if big else (0.1, 0.2, 0.3)):
                dirs = [tang, (-tang[0], -tang[1])] if tang else [(math.cos(i * math.pi / 4), math.sin(i * math.pi / 4)) for i in range(8)]
                cands += [(base[0] + d[0] * r_, base[1] + d[1] * r_) for d in dirs]
            if wall_n:                                            # a piece against a wall may also stand off it: big-glass frames, pilasters and casings stick out 5-20 cm (S33: 'collision:existing' x7)
                for dn in (0.06, 0.12, 0.2, 0.3):
                    cands += [(base[0] + wall_n[0] * dn + tang[0] * ts, base[1] + wall_n[1] * dn + tang[1] * ts) for ts in (0.0, 0.15, -0.15, 0.3, -0.3)]
            if not tang:                                          # no wall to hug: also try sliding towards the room's centre (a piece planned right at a wall line may overhang it)
                cx0, cy0 = self.centre.x, self.centre.y
                vx, vy = cx0 - base[0], cy0 - base[1]; vl = math.hypot(vx, vy) or 1.0
                cands += [(base[0] + vx / vl * r_, base[1] + vy / vl * r_) for r_ in (0.1, 0.2, 0.3, 0.45, 0.6)]
            zone_ = [] if (cat in ("rug", "round_rug", "raised_platform", "bar_portal", "mezzanine", "copper_duct") or mcat in self.WALL_MOUNTED) else self.obstacles                          # a rug is a floor covering: nothing blocks it and it blocks nothing (the footprint test still needs it on the floor)
            if mcat in self.WALL_MOUNTED or (cat == "tv_stand" and os.environ.get("ROOM_TV_AVOID_WINDOW") == "1"):                         # (H2 r17 LAY-01: a TV console + TV standing in front of the curtained window: the same slide-clear rule) a hung display / board never covers a window (H2 r7: the TV across a side window): drop candidates whose span on a wall overlaps a window span
                ww_ = o.dimensions[1]; wins_ = {wd_["id"]: [b_ for b_ in wd_.get("blocked", []) if b_[2] in ("window", "door")] for wd_ in self.doc.get("walls", [])}
                def _on_win(pt_):
                    for k_, (a2_, t2_, n2_, L2_) in self.walls.items():
                        rel_ = Vector((pt_[0], pt_[1], 0)) - a2_
                        if abs(rel_.dot(n2_)) < (0.95 if os.environ.get("ROOM_TV_AVOID_WINDOW") == "1" else 0.5) and any(b0_ - ww_ / 2 - (((0.3 if os.environ.get("ROOM_TV_AVOID_WINDOW") == "1" else 0.45)) if _k == "window" else 0.1) < rel_.dot(t2_) < b1_ + ww_ / 2 + (((0.3 if os.environ.get("ROOM_TV_AVOID_WINDOW") == "1" else 0.45)) if _k == "window" else 0.1) for b0_, b1_, _k in wins_.get(k_, [])):
                            return True
                    return False
                free_ = [c_ for c_ in cands if not _on_win(c_)]
                if not free_:                                     # the window + door span is wider than the slide candidates (H2 r10: a 1 m TV, a 1.04 m window): slide along that wall in 0.3 m steps, nearest clear spot first
                    for k_, (a2_, t2_, n2_, L2_) in self.walls.items():
                        if abs((Vector((base[0], base[1], 0)) - a2_).dot(n2_)) < (0.95 if os.environ.get("ROOM_TV_AVOID_WINDOW") == "1" else 0.5):
                            free_ = [(base[0] + t2_.x * d_, base[1] + t2_.y * d_) for d_ in sorted((s_ * 0.3 * q_ for q_ in range(1, 14) for s_ in (1, -1)), key=abs)
                                     if 0.4 < (Vector((base[0], base[1], 0)) - a2_).dot(t2_) + d_ < L2_ - 0.4 and not _on_win((base[0] + t2_.x * d_, base[1] + t2_.y * d_))]
                            break
                cands = free_ or cands
            hit = next(((px, py) for px, py in cands if fr._place(o, px, py, yaw, self.room, zone_, front)), None)
            if hit is not None:
                placed += 1; self.stats["furniture_added"] += 1
                lid = str(e.get("id") or f"L{placed}")
                if e.get("_ncols") and side_wall is not None and e.get("_s") is not None:
                    wall_fronts.setdefault(side_wall, []).append((float(e["_s"]) - e["_ncols"] * 0.175, float(e["_s"]) + e["_ncols"] * 0.175, 0.36))
                o["src"] = "layout:" + lid                       # provenance: this object is in the reference
                if e.get("lift"):                                # layout "lift": metres above the floor (plants on the atrium mezzanine deck)
                    o.location.z += float(e["lift"])
                if mcat in self.WALL_MOUNTED:                    # a hung item (TV, board, rail) is lifted to its mount height and blocks no floor space
                    o.location.z += self.WALL_MOUNTED[mcat]
                if mcat in ("mezzanine", "copper_duct"):         # overhead structures (atrium): they hang above the floor, so they take the platform's place in the layout but block no floor space
                    if self.obstacles:
                        self.obstacles.pop()
                    if mcat == "copper_duct":
                        o.location.z += 5.9 if os.environ.get("ROOM_ATRIUM_FIX") == "1" else 5.4         # _place drops the object's lowest point to the floor: the tube centre ends at its radius, so 5.9 puts a 0.9 m tube centre at ~6.35 m
                    elif os.environ.get("ROOM_ATRIUM_FIX") == "1":
                        o.location.z += 3.95                     # mezzanine: _place dropped the fascia's underside to the floor (r3: a 1 m plinth on the ground); deck underside at ~3.95 m
                if mcat == "desk_bench":
                    bb_ = self.obstacles.pop() if self.obstacles else None
                    self._pod_chairs(o)
                    if bb_ is not None:
                        self.obstacles.append(bb_)
                self.ids[lid] = (o, front)                       # so the program's lived_in can say on: <id> ...
                self.layout_cat_ids = getattr(self, "layout_cat_ids", {})
                self.layout_cat_ids.setdefault(cat, lid)         # ... or on: @<category> (the first item of that category)
                self.layout_items = getattr(self, "layout_items", [])
                self.layout_items.append((lid, cat))
                if cat not in ("rug", "round_rug", "raised_platform", "bar_portal", "mezzanine", "copper_duct") and self.obstacles:
                    labels[self.obstacles[-1]] = cat
                if cat == "bar_portal":                                  # a frame is walkable between its posts: only the two posts and the step block
                    mw = o.matrix_world
                    for (cx_, cy_, sx_, sy_) in ((0.0, 2.01, 0.2, 0.18), (0.0, -2.01, 0.2, 0.18), (-0.3, 0.0, 0.55, 3.84)):        # BarPortalFactory: two posts + the stone step, local metres
                        qs = [mw @ Vector((cx_ + dx_ * sx_ / 2, cy_ + dy_ * sy_ / 2, 0.0)) for dx_ in (-1, 1) for dy_ in (-1, 1)]
                        bx_ = (min(q.x for q in qs), max(q.x for q in qs), min(q.y for q in qs), max(q.y for q in qs), self.room.z, self.room.z + 0.5)
                        self.obstacles.append(bx_); labels[bx_] = "bar_portal"
                fp_ = fr.footprint(o)
                if cat == "raised_platform":
                    platforms.append((fp_[0], fp_[1], fp_[2], fp_[3], min(fp_[5] - fp_[4], 0.3)))              # the DECK height: the footprint's full height includes the 1 m balustrade, which lifted chairs and tables ~1 m (S34 r17: 98 cm over the platform, caught by support_check)
                elif cat not in ("rug", "round_rug", "mezzanine", "copper_duct"):
                    pcx, pcy = (fp_[0] + fp_[1]) / 2, (fp_[2] + fp_[3]) / 2
                    for px0, px1, py0, py1, ph in platforms:                         # standing on the platform: lifted by its height, when MOST of the footprint is on it (a seat half off the edge stays on the floor)
                        ov_ = max(0.0, min(fp_[1], px1) - max(fp_[0], px0)) * max(0.0, min(fp_[3], py1) - max(fp_[2], py0))
                        if ov_ >= 0.5 * max((fp_[1] - fp_[0]) * (fp_[3] - fp_[2]), 1e-6):
                            o.location.z += ph
                            break
                if cat in TABLES:
                    f_ = fr.footprint(o)
                    anchors.append({"cat": cat, "id": lid, "tx": x, "ty": y, "dx": (f_[0] + f_[1]) / 2 - x, "dy": (f_[2] + f_[3]) / 2 - y,
                                    "box": (f_[0] - ((f_[0] + f_[1]) / 2 - x), f_[1] - ((f_[0] + f_[1]) / 2 - x), f_[2] - ((f_[2] + f_[3]) / 2 - y), f_[3] - ((f_[2] + f_[3]) / 2 - y))})
            else:
                dropped[cat] = dropped.get(cat, 0) + 1
                if cat in ("desk", "office_desk"):
                    gone_desks_.append(lpl.to_world(fr_, float(e["u"]), float(e["v"])))
                rz = yaw - math.atan2(front[1], front[0])                                     # why: the same footprint test fr._place applies, at the first candidate
                R3 = Matrix.Rotation(rz, 3, "Z") @ Matrix.Diagonal(o.scale)
                pts = [R3 @ p for p in fr._local_points(o)]
                f0 = (min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts), min(p.z for p in pts), max(p.z for p in pts))
                ox_, oy_ = base[0] - (f0[0] + f0[1]) / 2, base[1] - (f0[2] + f0[3]) / 2
                f = (f0[0] + ox_, f0[1] + ox_, f0[2] + oy_, f0[3] + oy_, self.room.z, self.room.z + (f0[5] - f0[4]))
                cs_ = [(f[0] + 0.05, f[2] + 0.05), (f[1] - 0.05, f[2] + 0.05), (f[0] + 0.05, f[3] - 0.05), (f[1] - 0.05, f[3] - 0.05), ((f[0] + f[1]) / 2, (f[2] + f[3]) / 2)]
                if not all(self.room.on_floor(cx, cy) for cx, cy in cs_):
                    reason = "off_floor"
                else:
                    b_ = next((b for b in zone_ if fr._overlap(f, b)), None)
                    reason = "collision:" + labels.get(b_, "existing") if b_ is not None else "unknown"
                    if reason == "collision:existing":                                         # name what it is
                        names_ = [rd._factory(t_.name) for t_ in rd._tops() if t_.type == "MESH" and not t_.hide_render and all(abs(u_ - v_) < 0.03 for u_, v_ in zip(fr.footprint(t_)[:4], b_[:4]))]       # the object whose footprint IS the obstacle
                        reason += ":" + (",".join(sorted(set(names_)))[:60] or "?")
                why_.append({"category": cat, "u": e.get("u"), "v": e.get("v"), "reason": reason, **self._drop_blockers(cands, f0, f, zone_, labels, fr_), **({"dbg": dbg_} if dbg_ else {})})
                bpy.data.objects.remove(o, do_unlink=True)
        for dx_, dy_ in gone_desks_:                             # seat-follows-table: a chair or wall TV standing within 1.8 m of a desk that was dropped is dropped too (H2 r9: a chair facing a wall TV with no desk)
            for lid_, cat_ in list(getattr(self, "layout_items", [])):
                if cat_ in ("office_chair", "desk_chair", "tv_stand") and lid_ in self.ids:
                    f_ = fr.footprint(self.ids[lid_][0])
                    if (((f_[0] + f_[1]) / 2 - dx_) ** 2 + ((f_[2] + f_[3]) / 2 - dy_) ** 2) ** 0.5 < 1.8:
                        bpy.data.objects.remove(self.ids[lid_][0], do_unlink=True); del self.ids[lid_]
                        self.layout_items.remove((lid_, cat_)); placed -= 1; dropped[cat_] = dropped.get(cat_, 0) + 1
                        why_.append({"category": cat_, "reason": "desk_dropped"})
        self.stats["layout_placed"] = placed
        self.stats["layout_dropped"] = dropped
        self.stats.setdefault("layout_by_room", {})[str(self.doc.get("id"))] = {"placed": placed, "dropped": dropped, "reasons": why_}      # a floor has many layout rooms: the flat keys below keep only the last one
        self.stats["layout_drop_reasons"] = why_            # [{category, u, v, reason: off_floor | collision:<category | door_keepout | existing> | no_asset | unknown}]
        _log(f"layout: {placed}/{len(items)} placed, dropped {dropped}")
        if os.environ.get("ROOM_LAYOUT_STOCK") == "1" and proc_assets_kit().VENUE in ("grocery", "convenience", "pharmacy"):      # S37 r1: a layout's gondolas / back-bar boards stood bare (the stocking lives in _fill_gondolas, which a layout room never reaches)
            for sid_, (o_, _f) in list(self.ids.items()):
                if ":" not in sid_ and rd._factory(o_.name) in self.MERCH_HOSTS + ("BackBarShelfFactory",):
                    daily_ = sid_ in (os.environ.get("ROOM_STOCK_DAILY") or "").split(",")
                    if daily_:                                                                      # S37 r4: daily needs = tissue boxes + toiletry bottles + jars (+ library towels with ROOM_STOCK_TOWELS=1)
                        dm_ = [(_safe_cls("inf:FoodBoxFactory"), 3.0), (_safe_cls("inf:BottleFactory"), 3.0), (_safe_cls("inf:JarFactory"), 0.7)]
                        if os.environ.get("ROOM_STOCK_TOWELS") == "1":
                            dm_.append((_safe_cls("inf:LibTowelFactory"), 5.0))
                        self._mix_override = [(c_, w_) for c_, w_ in dm_ if c_ is not None]
                    self.fill({"on": sid_, "category": "groceries"}, _cls(catalog.LIVED_IN["groceries"]["src"]))
                    self._mix_override = None
        if os.environ.get("ROOM_TV_AVOID_WINDOW") == "1":           # H2 r20 LAY-02: a TV slid off the window landed on a framed picture hung earlier -> a picture the TV overlaps (xy box + 0.05 m, same height band) is removed
            tvs_ = [o_ for o_, _f in self.ids.values() if rd._factory(o_.name) in ("WallDisplayFactory", "TVStandFactory")]
            bbw_ = lambda o_: [o_.matrix_world @ Vector(c_) for c_ in o_.bound_box]
            for tv_ in tvs_:
                tb_ = bbw_(tv_); t0_ = (min(q.x for q in tb_) - 0.05, max(q.x for q in tb_) + 0.05, min(q.y for q in tb_) - 0.05, max(q.y for q in tb_) + 0.05, min(q.z for q in tb_), max(q.z for q in tb_))
                for ar_ in [a_ for a_ in bpy.data.objects if a_.type == "MESH" and a_.parent is None and rd._factory(a_.name) in ("WallArtFactory", "MirrorFactory")]:
                    ab_ = bbw_(ar_)
                    if min(q.x for q in ab_) < t0_[1] and max(q.x for q in ab_) > t0_[0] and min(q.y for q in ab_) < t0_[3] and max(q.y for q in ab_) > t0_[2] and min(q.z for q in ab_) < t0_[5] and max(q.z for q in ab_) > t0_[4]:
                        bpy.data.objects.remove(ar_, do_unlink=True); self.stats["tv_art_removed"] = self.stats.get("tv_art_removed", 0) + 1
        if os.environ.get("ROOM_BATH_COMPACT") == "1" and self.doc.get("type") in ("bathroom", "restroom") and (dropped.get("toilet") or dropped.get("washbasin")):      # H3 r12: what the reference position could not take goes to any free wall spot
            fix_ = ([{"id": "fix_wc", "category": "wc", "relation": "against_wall", "count": 1}] if dropped.get("toilet") else []) + ([{"id": "fix_basin", "category": "wash_basin", "relation": "against_wall", "count": 1}] if dropped.get("washbasin") else [])
            left_ = self.place_all(fix_)
            still_ = []
            for it_, _r in left_:                                # a squeeze: every wall, every 10 cm, 3 standoffs, facing into the room (H3 r14: a basin collided with the door keepout and the shower at its layout spot and in the generic wall search)
                if not self._squeeze({"wc": "wc", "wash_basin": "wash_basin"}.get(it_["category"], it_["category"])):
                    still_.append(it_)
            self.stats["bath_fix"] = {str(self.doc.get("id")): {"asked": [f_["category"] for f_ in fix_], "failed": [x_["category"] for x_ in still_]}}

    def _squeeze(self, cat) -> bool:
        """One piece on the first free wall spot: walls W / E / S / N in turn, every 10 cm along them, 3 standoffs, facing into the room. A small room's basin is retried at 0.8 and 0.65 of its size, and last of all ignoring the zero-height door-swing boxes (a wall-hung basin above 0.75 m does not block a swing at hand height; H3 r15 bathroom_0/3)."""
        o, front = self._make(cat)
        if o is None:
            return False
        x0, x1, y0, y1 = self.room.box
        k0 = tuple(o.scale)
        for k_, ign_ in ((1.0, False), (0.8, False), (0.65, False), (0.65, True)):
            if k_ != 1.0 and cat not in ("wash_basin", "vanity"):
                break
            o.scale = (k0[0] * k_, k0[1] * k_, k0[2] * k_); bpy.context.view_layer.update()
            zone_ = [b_ for b_ in self.obstacles if not (ign_ and b_[4] == b_[5] == 0)]
            for (nx, ny) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yaw = math.atan2(ny, nx)
                n_ = int(((y1 - y0) if nx else (x1 - x0)) / 0.1)
                for q in range(2, n_ - 1):
                    for dd in (0.2, 0.26, 0.34):
                        if nx:
                            px, py = (x0 + dd if nx > 0 else x1 - dd), y0 + q * 0.1
                        else:
                            px, py = x0 + q * 0.1, (y0 + dd if ny > 0 else y1 - dd)
                        if fr._place(o, px, py, yaw, self.room, zone_, front):
                            self.stats["furniture_added"] += 1
                            return True
        bpy.data.objects.remove(o, do_unlink=True)
        return False

    def _drop_blockers(self, cands, f0, f, zone_, labels, fr_):
        """Every candidate position the placer tried for a dropped item, summarised for the plan's author: how many were off the floor and the objects that blocked the rest, each as layout (u, v) and its size in
        metres along the wall (w) and into the room (d): {"tried": n, "off_floor": k, "blockers": [{"what", "u", "v", "w", "d", "n"}]} (top 3 by how many candidates they blocked)."""
        O, R, nn, W, D, _w = fr_
        blk, nof = {}, 0
        for cx_, cy_ in cands[:60]:
            ox2, oy2 = cx_ - (f0[0] + f0[1]) / 2, cy_ - (f0[2] + f0[3]) / 2
            g = (f0[0] + ox2, f0[1] + ox2, f0[2] + oy2, f0[3] + oy2, f[4], f[5])
            if not all(self.room.on_floor(x_, y_) for x_, y_ in ((g[0] + 0.05, g[2] + 0.05), (g[1] - 0.05, g[2] + 0.05), (g[0] + 0.05, g[3] - 0.05), (g[1] - 0.05, g[3] - 0.05), ((g[0] + g[1]) / 2, (g[2] + g[3]) / 2))):
                nof += 1
                continue
            b2 = next((b for b in zone_ if fr._overlap(g, b)), None)
            if b2 is not None:
                blk[b2] = blk.get(b2, 0) + 1
        out = []
        for b2, k in sorted(blk.items(), key=lambda kv: -kv[1])[:3]:
            cx2, cy2 = (b2[0] + b2[1]) / 2 - O[0], (b2[2] + b2[3]) / 2 - O[1]
            dx2, dy2 = b2[1] - b2[0], b2[3] - b2[2]
            out.append({"what": labels.get(b2, "existing"), "box": [round(v, 2) for v in b2[:4]], "objs": sorted({rd._factory(t_.name)[:24] for t_ in rd._tops() if t_.type == "MESH" and (lambda g_: g_[0] < (b2[0] + b2[1]) / 2 < g_[1] and g_[2] < (b2[2] + b2[3]) / 2 < g_[3])(fr.footprint(t_))})[:4], "u": round((cx2 * R[0] + cy2 * R[1]) / W, 3), "v": round((cx2 * nn[0] + cy2 * nn[1]) / D, 3),
                        "w": round(abs(R[0]) * dx2 + abs(R[1]) * dy2, 2), "d": round(abs(nn[0]) * dx2 + abs(nn[1]) * dy2, 2), "n": k})
        cu = [((x_ - O[0]) * R[0] + (y_ - O[1]) * R[1]) / W for x_ in (f[0], f[1]) for y_ in (f[2], f[3])]
        cv = [((x_ - O[0]) * nn[0] + (y_ - O[1]) * nn[1]) / D for x_ in (f[0], f[1]) for y_ in (f[2], f[3])]
        return {"tried": min(len(cands), 60), "off_floor": nof, "blockers": out, "foot_uv": [round(min(cu), 3), round(max(cu), 3), round(min(cv), 3), round(max(cv), 3)]}

    def _layout_lived(self, it):
        """A layout / program table-top item. The big counter pieces (pastry_case, espresso_machine) stand at a fixed slot on the counter top, 0.45 m in from an end (the generic top finder logged 'no fit' for them in
        cafe loop r1 and in S35: no pastry case on the counter), the rest go through lived_in."""
        if it.get("category") in ("pastry_case", "espresso_machine") and it.get("on") in self.ids:
            C = self.ids[it["on"]][0]
            Lc = C.dimensions[1] / max(C.scale.y, 1e-6)
            top = max((C.matrix_world.inverted() @ (C.matrix_world @ Vector(q))).z for q in C.bound_box)
            end = 1 if it["category"] == "pastry_case" else -1
            o = self.spawn(_cls(catalog.LIVED_IN[it["category"]]["src"]))
            if o is None:
                return
            o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, C.matrix_world.to_euler().z + (math.pi if it["category"] == "espresso_machine" else 0))
            bpy.context.view_layer.update()
            f = fr.footprint(o); p = C.matrix_world @ Vector((0.0, end * max(0.0, Lc / 2 - 0.45), top))
            o.location += Vector((p.x - (f[0] + f[1]) / 2, p.y - (f[2] + f[3]) / 2, p.z - f[4]))
            bpy.context.view_layer.update()
            self.stats["lived_in_added"] = self.stats.get("lived_in_added", 0) + 1
            return
        self.lived_in(it)

    def _run_layout(self, plan):
        """A room with a floor-plan layout is FIXED: only the layout's pieces, the program's own lived_in, the kit's window curtains and the finishing passes. No LLM plan, density scatter, venue auto-adds,
        table guard or break-table rule."""
        import provenance as pv
        allow = set(plan.get("auto_allow") or [])                  # kit room_program[id]["auto_allow"]: the automatic passes this reference-authoritative room still wants
        self.toss = []
        self._fill_layout(plan)
        self.drop_spares()
        if os.environ.get("ROOM_DESK_RETRY") == "1":                # H3 r17 CNT-01: a layout desk whose chair collided with the desk's own 1.4 m footprint stood chairless and bare -> a chair on the first free side of it, a notebook + lamp on top
            try:
                for lid_, cat_ in list(getattr(self, "layout_items", [])):
                    if cat_ != "desk" or lid_ not in self.ids:
                        continue
                    d_o, d_f = self.ids[lid_]; fp_ = fr.footprint(d_o)
                    if any(rd._factory(o_.name) in ("OfficeChairFactory", "TaskChairFactory", "AboOfficechairFactory", "DeskChairFactory") or "hair" in rd._factory(o_.name) and abs((fr.footprint(o_)[0] + fr.footprint(o_)[1]) / 2 - (fp_[0] + fp_[1]) / 2) < 1.6 and abs((fr.footprint(o_)[2] + fr.footprint(o_)[3]) / 2 - (fp_[2] + fp_[3]) / 2) < 1.6 for o_, _f in self.ids.values() if o_ is not d_o):
                        continue
                    ch_o, ch_f = self._make("desk_chair")
                    if ch_o is None:
                        continue
                    cx_, cy_ = (fp_[0] + fp_[1]) / 2, (fp_[2] + fp_[3]) / 2; hw_, hh_ = (fp_[1] - fp_[0]) / 2, (fp_[3] - fp_[2]) / 2; ok_ = False
                    for (sx_, sy_) in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                        for off_ in (0.55, 0.7, 0.85):
                            px_, py_ = cx_ + sx_ * (hw_ + off_ if sx_ else 0.0), cy_ + sy_ * (hh_ + off_ if sy_ else 0.0)
                            if fr._place(ch_o, px_, py_, math.atan2(-sy_, -sx_), self.room, self.obstacles, ch_f):
                                ok_ = True; break
                        if ok_:
                            break
                    if ok_:
                        self.ids[f"desk_chair_fix{lid_}"] = (ch_o, ch_f); self.stats["furniture_added"] += 1
                    else:
                        bpy.data.objects.remove(ch_o, do_unlink=True)
                    for cat2_ in ("notebook", "table_lamp"):
                        try:
                            self.lived_in({"category": cat2_, "on": lid_, "count": 1, "pose": "placed"})
                        except Exception as ex_:               # noqa: BLE001
                            _log(f"desk fix {cat2_}: {ex_!r}"[:100])
            except Exception as ex_:                           # noqa: BLE001 -- an extra
                _log(f"desk chair fix: {ex_!r}"[:120])
        for it in plan.get("lived_in", []):
            on_ = str(it.get("on", ""))
            if on_.startswith("@"):                                   # "@counter" -> the layout's first counter
                on_ = getattr(self, "layout_cat_ids", {}).get(on_[1:])
                if on_ is None:
                    continue
                it = {**it, "on": on_}
            with pv.tag("program:lived_in"):
                self._layout_lived(it)
        if ("window_curtains" in allow or getattr(self, "_want_curtains", False)) and proc_assets_kit().STYLE.get("window_curtains") and self.doc.get("type") in proc_assets_kit().STYLE["window_curtains"]:
            self._window_curtains()
        if "table_dressing" in allow:                              # auto_allow "table_dressing": every layout table gets a few drinks / tableware items (cafe table 2, dining / break table 4-6)
            import random as _rnd
            LOUNGE_ = ("coffee_table", "side_table", "lounge_table", "low_table", "round_low_table", "low_round_table")      # O5 r7 / H3: 'the low lounge / meeting table is bare'
            MEET_ = ("meeting_table", "conference_table")
            for lid, cat_ in getattr(self, "layout_items", []):
                if cat_ in LOUNGE_:                                # a lounge mix: 2-4 of books / magazines, cups, a vase or a small plant, a fruit bowl; a laptop now and then
                    mix_ = ["book_stack", "open_book", "mug", "mug", "vase", "small_plant", "fruit_bowl"]
                    picks_ = []
                    for c_ in self.rng.sample(mix_, k=self.rng.randint(2, 4)):
                        if c_ in ("vase", "small_plant", "fruit_bowl") and any(q_ in ("vase", "small_plant", "fruit_bowl") for q_ in picks_):
                            continue                               # one centrepiece
                        picks_.append(c_)
                    if self.rng.random() < 0.15:
                        picks_.append("open_laptop")
                    with pv.tag("pass:table_dressing"):
                        for c_ in picks_:
                            self.lived_in({"category": c_, "on": lid})
                    continue
                if cat_ in MEET_:
                    with pv.tag("pass:table_dressing"):
                        for c_ in self.rng.choices(["takeaway_cup", "mug", "phone", "snack", "open_laptop", "open_book"], k=self.rng.randint(3, 5)):
                            self.lived_in({"category": c_, "on": lid})
                    continue
                if cat_ not in ("cafe_table", "dining_table", "break_table"):
                    continue
                n_ = self.rng.randint(1, 3) if cat_ == "cafe_table" else self.rng.randint(4, 6)
                if os.environ.get("ROOM_DRESS_VARIETY") == "1":     # S34 (user 10-24: 'the small objects repeat'): every table draws its OWN distinct set from a wide pool (cups, tumblers, plates, a cake dome, candle, vase, books, phone, notebook, plant, fruit), no repeats on one table
                    pool_ = ["mug", "takeaway_cup", "plate", "wine_glass", "bud_vase", "candle", "cake_dome", "phone", "open_book", "book_stack", "notebook", "small_plant", "fruit_bowl", "snack", "mug"]
                    picks_ = self.rng.sample(pool_, k=min(len(pool_), n_ + 1 if cat_ == "cafe_table" else n_))
                    with pv.tag("pass:table_dressing"):
                        for c_ in picks_:
                            self.lived_in({"category": c_, "on": lid})
                    continue
                with pv.tag("pass:table_dressing"):
                    for c_ in self.rng.choices(["takeaway_cup", "plate", "mug", "bud_vase", "plate"], k=n_):
                        self.lived_in({"category": c_, "on": lid})
        if "shelf_stock" in allow:                                 # auto_allow "shelf_stock": every layout backbar_shelf is stocked (bottles, glasses); bookshelves hold books
            for lid, cat_ in getattr(self, "layout_items", []):
                with pv.tag("pass:shelf_stock"):
                    if cat_ == "backbar_shelf":
                        self.fill({"on": lid, "category": "backbar_stock"}, _cls(catalog.LIVED_IN["backbar_stock"]["src"]))
                    elif cat_ in ("bookshelf", "office_bookcase"):
                        sc_ = proc_assets_kit().STYLE.get("bookshelf_stock") or "book_stack"             # kit bookshelf_stock="dry_goods": a bakery / shop rack drawn as 'bookshelf' holds packaged goods, not books (S35 CNT-04)
                        self.fill({"on": lid, "category": sc_}, _cls(catalog.LIVED_IN[sc_]["src"]))
        if "traces" in allow:
            self.traces(plan)
        self.appliance_finish()
        settle(self.toss, self.room, self.rng, self.stats)

    def run(self, plan):
        if plan.get("layout"):                                   # floor-plan placement (kit room_program[id]['layout']): nothing else furnishes this room
            return self._run_layout(plan)
        if LAB and self.doc.get("type") == "hallway":            # chambers and gas racks along the corridor wall first
            self._fill_lab_corridor(plan)
        if self.mode:                                            # the mode's layout goes first; the plan's categories it owns are dropped
            _lm = self._fill_mode(plan)
            plan = {**plan, "furniture": [f for f in plan.get("furniture", []) if f["category"] not in getattr(_lm, "DROP", ())]}
        if MUSEUM:                                               # the museum layout goes first; the plan's plain display tables / counters etc. are dropped
            self._fill_museum(plan)
            drop = {"display_table", "clothing_rack", "fitting_room", "wall_gondola", "mirror", "counter", "armchair", "rug"}
            plan = {**plan, "furniture": [f for f in plan.get("furniture", []) if f["category"] not in drop]}
        if CLINIC_LOBBY and self.doc.get("type") == "clinic-reception":   # the lobby layout goes first; the plan's benches / desk / chair / sofa group are dropped
            self._fill_clinic_lobby(plan)
            drop = {"waiting_bench", "reception_desk", "desk_chair", "filing_cabinet", "sofa", "armchair", "coffee_table", "rug", "floor_plant"}
            plan = {**plan, "furniture": [f for f in plan.get("furniture", []) if f["category"] not in drop]}
        if BOOKSTORE:                                            # the book layout goes first; the plan's plain display tables / fitting rooms / gondolas are dropped
            self._fill_bookstore(plan)                           # (bookstore r1: 16 of ~45 placed, the planner's own bare tables took the floor)
            drop = {"display_table", "fitting_room", "wall_gondola", "mirror"}
            plan = {**plan, "furniture": [f for f in plan.get("furniture", []) if f["category"] not in drop]}
        if WINEPUB:                                              # the deterministic layout goes first, the plan's standard cafe seating is dropped
            self._fill_winepub(plan)
            drop = {"cafe_table", "cafe_chair", "banquette_row", "bar_stool", "window_bar", "break_table", "backbar_shelf"}
            if self.stats.get("winepub", {}).get("bar_placed"):
                drop |= {"counter", "coffee_bar"}
            plan = {**plan, "furniture": [f for f in plan.get("furniture", []) if f["category"] not in drop]}
        if FLAGSHIP and self.doc.get("area_m2", 0) > 150:        # the deterministic hall layout goes first (flagship r6: 14 of 36 placed, 18 refused as
            self._fill_flagship(plan)                            # 'obstacle' = the planner's own 12-16 pieces); the plan then fills around it
            drop = {"clothing_rack", "display_table", "mirror", "fitting_room", "wall_gondola"}
            if self.stats.get("flagship_layout", {}).get("counter_placed"):
                drop.add("counter")
            plan = {**plan, "furniture": [f for f in plan.get("furniture", []) if f["category"] not in drop]}
        if ROOFTOP:                                              # the deterministic layout goes first, before the plan's standard cafe seating takes the floor
            self._fill_rooftop(plan)                             # (rooftop r1: 5 of 25 layout pieces placed when it ran after the plan and fill_empty)
            drop = {"cafe_table", "cafe_chair", "banquette_row", "bar_stool", "window_bar", "break_table"}
            if self.stats.get("rooftop", {}).get("counter_placed"):
                drop.add("counter")
            plan = {**plan, "furniture": [f for f in plan.get("furniture", []) if f["category"] not in drop]}
        # the zone that makes the room what it is: added when the plan left it out (a break room planned without its pantry, 2026-10-16)
        need = None if plan.get("fixed") else self.REQUIRED_ZONE.get(self.doc.get("type", ""))
        if need and need[0] in plan.get("forbid", []):            # the kit forbids the venue's stereotype zone (S32 ramen: a coffee_bar was forced, so the counter came with an espresso machine and a pastry case)
            need = None      # a FIXED program already says what the room is (G/H kitchen: a pantry run + microwave were force-added beside the steel run)
        if need and not any(f["category"] == need[0] for f in plan.get("furniture", [])):
            plan = {**plan, "furniture": [{"id": "req_" + need[0], "category": need[0], "relation": need[1]}] + plan.get("furniture", [])}
            self.stats["zones_forced"] = self.stats.get("zones_forced", 0) + 1
            _log(f"required zone {need[0]} added")
        for cat, rel in ([] if ((CLINIC_LOBBY and self.doc.get("type") == "clinic-reception") or MUSEUM or BOOKSTORE or ROOFTOP or WINEPUB or self.mode) else self.REQUIRED_ITEMS.get(self.doc.get("type", ""), [])):   # the pieces that make the room what it is (the lobby brings its own desk and seating; D3 r28: the required reception_desk + waiting_bench came back)
            have = [f for f in plan.get("furniture", []) if f["category"] == cat or (cat == "bed" and f["category"] == "single_bed") or (cat == "vanity" and f["category"] in ("oak_vanity", "oak_vanity_long"))]   # twin beds are beds: P2b r3 added a REQUIRED double bed to the twin suite and it was dropped for lack of room
            if rel == "near_door" and have:                      # the checkout stands by the door whatever the plan said
                plan = {**plan, "furniture": [({**f, "relation": "near_door", "target": None} if f is have[0] else f) for f in plan["furniture"]]}
            elif not have:
                extra = {"count": 4, "wall": max(self.walls, key=lambda k: self.walls[k][3]) if self.walls else None} if rel == "row" else {}
                plan = {**plan, "furniture": [{"id": "req_" + cat, "category": cat, "relation": rel, **extra}] + plan.get("furniture", [])}
                _log(f"required {cat} added")
        if self.doc.get("type") == "dental-room":              # the chair stands free in the room, whatever the plan says (clinic r3)
            plan = {**plan, "furniture": [({**f, "relation": "center", "target": None} if f["category"] == "dental_chair" else f)
                                          for f in plan.get("furniture", [])]}
        if self.doc.get("type") in ("clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy"):
            # one plant at most (clinic r7: an olive grove on the physio floor), and the reception chair on the staff side
            desks = {f["id"] for f in plan.get("furniture", []) if f["category"] == "reception_desk"}
            n_pl = [0]
            def clin(f):
                if f["category"] == "floor_plant":                # one plant in reception, none in treatment rooms (r17: 'a big green planter')
                    n_pl[0] += f.get("count", 1)
                    return n_pl[0] <= (1 if self.doc.get("type") == "clinic-reception" else proc_assets_kit().STYLE.get("plant_count", 0))      # kit plant_count: S20's ref has plants in the physio hall
                return True
            if self.doc.get("type") == "physio-room":            # an open gym floor: no curtain (clinic r20: it stood mid-room between the
                if not proc_assets_kit().STYLE.get("keep_curtains"):                # kit key keep_curtains: a large physio hall (S20 ref: sage curtains between the beds) keeps them
                    plan = {**plan, "furniture": [f for f in plan["furniture"] if f["category"] != "privacy_curtain"]}   # bike and the bars, 3 of 3)
                # two plinths at least, on the walls (r29: 'one bed in a large room', 3 of 3; 'a bed floating mid-room')
                plan = {**plan, "furniture": [({**f, "count": max(2, f.get("count", 1)), "relation": "against_wall", "target": None}
                                               if f["category"] == "exam_table" else f) for f in plan["furniture"]]}
                plan = {**plan, "furniture": [({**f, "relation": "against_wall", "target": None} if f["category"] in ("rolling_stool", "clinic_desk", "medical_cabinet", "filing_cabinet") else f) for f in plan["furniture"]]}   # a stool has no relation of its own: on the free floor it found no spot (S20 r37 plan_dropped rolling_stool 2)
                # the bars first, their lane reserved at once: the beds came first and the bars ran along them (clinic r22: 'no
                # therapist could stand at a bed', 3 of 3)
                plan = {**plan, "furniture": sorted(plan["furniture"], key=lambda f: f["category"] != "parallel_bars")}
            curt = [f for f in plan.get("furniture", []) if f["category"] == "privacy_curtain"]
            if len(curt) > 1:                                    # one curtain per couch is enough (r15: two, the second on a wall)
                plan = {**plan, "furniture": [f for f in plan["furniture"] if f["category"] != "privacy_curtain" or f is curt[0]]}
            couches = [f["id"] for f in plan.get("furniture", []) if f["category"] == "exam_table"]
            if couches:                                          # every curtain hangs round a couch (clinic r12: the curtain ran along a far
                plan = {**plan, "furniture": [({**f, "target": couches[0]} if f["category"] == "privacy_curtain"   # wall, the couch stood alone)
                                               and f.get("target") not in couches else f) for f in plan["furniture"]]}
            wb = [0]                                             # one whiteboard at most (physio r31: 'three boards -- a classroom')
            def one_board(f):
                if f["category"] in ("whiteboard", "wall_display"):
                    wb[0] += 1
                    return wb[0] == 1
                return True
            plan = {**plan, "furniture": [f for f in plan["furniture"] if one_board(f)]}
            # no plants on clinic counters and worktops (clinic r27: 'a potted plant on the reception counter -- a design studio')
            plan = {**plan, "lived_in": [x for x in plan.get("lived_in", []) if "plant" not in x.get("category", "")]}
            if self.doc.get("type") == "clinic-reception" and desks:   # benches after the first face the counter (clinic r23-r25:
                nb = [0]                                             # 'side-on to the desk', layout 6 in 3 rounds)
                def face_desk(f):
                    if f["category"] != "waiting_bench":
                        return f
                    nb[0] += 1
                    if nb[0] > 3:                                    # three rows at most (r27: 'four-five rows'; five wall rows + the island
                        # made '35-40 seats for a 3-chair practice', floor E3 r11, 3 of 3);
                                                                     # a 44-52 m2 lobby lines its walls with up to five (floor D3 r5: 'empty hall')
                        return None
                    if self.doc.get("area_m2", 0) >= 35:             # a floor's 44-52 m2 lobby: benches line the walls (floor D3 r4: rows
                        return {**f, "relation": "against_wall", "target": None, "count": 1}   # mid-floor 'at odd angles', 3 of 3)
                    return f if nb[0] == 1 else {**f, "relation": "facing", "target": sorted(desks)[0], "count": 1, "gap_m": 1.0}   # r27: 1.6 m
                    # crowded the counter front -- 'no queue space'

                plan = {**plan, "furniture": [g for g in (face_desk(f) for f in plan["furniture"]) if g is not None]}
                if self.doc.get("area_m2", 0) >= 35:             # a 44-52 m2 lobby seats 12-16 (floor D3 r7: 'only 6 seats for 4 GPs', 3/3)
                    nbn = sum(1 for f in plan["furniture"] if f["category"] == "waiting_bench")
                    plan = {**plan, "furniture": [f for f in plan["furniture"] if f["category"] != "filing_cabinet"] +   # no files on the
                            [{"id": f"bench_x{k}", "category": "waiting_bench", "relation": "against_wall"} for k in range(max(0, 2 - nbn))]}   # public side
            plan = {**plan, "furniture": [({**f, "relation": "behind"} if f["category"] == "desk_chair" and f.get("target") in desks else
                                           {**f, "relation": "against_wall", "gap_m": 1.05, "target": None}
                                           if f["category"] == "reception_desk" and self.doc.get("type") == "clinic-reception"   # not the pharmacy
                                                                                          # (shop r8: its counter floated among the gondolas)
                                           else f) for f in plan.get("furniture", []) if clin(f)]}
            # the counter stands 1.3 m off the wall with a staff zone behind it (clinic r11: flush on the wall, the staff chair found no
            # spot and the props sat on the hidden staff-side shelf -- 'a bare desk, no staff side')
        if self.doc.get("type") == "meeting-room":               # notepads, not hardback stacks, on a meeting table (floor A2 r7, 3 of 3)
            plan = {**plan, "lived_in": [x for x in plan.get("lived_in", []) if x.get("category") not in ("book_stack", "open_book")]}
        if self.doc.get("type") == "meeting-room":               # the zone seats every side; a bare table got 2-3 chairs on one side
            fs = plan.get("furniture", [])                      # (floor B: 'a desk with a TV, not a meeting room', 3 of 3)
            if not any(f["category"] == "meeting_set" for f in fs):   # always the set: a plan without a meeting table gave 'a narrow desk
                fs = [f for f in fs if f["category"] not in ("meeting_table", "desk_chair", "office_desk", "bar_stool", "conference_chair")]   # by the
                plan = {**plan, "furniture": [{"id": "req_meeting_set", "category": "meeting_set", "relation": "center"}] + fs}   # window' (C r7)
        if self.doc.get("type") in ("warehouse",) and not plan.get("fixed"):     # a FIXED program (G/H utility: wire racks, heater, mop sink) is not rewritten into stock shelves + pallets
            plan = self._warehouse_plan(plan)
            if any(f["category"] == "workbench" for f in plan["furniture"]):
                self._main_aisle(width=1.8)                      # a clear lane from the door through a packing room
        if self.doc.get("type") in ("convenience", "grocery"):  # baskets: one dropped on the floor at most, the rest stacked at the counter
            seen = [0]                                           # (shop r3: 'about 8 baskets lie scattered across the aisles')
            def keep(x):
                if x.get("category") == "basket" and x.get("on") == "floor":
                    seen[0] += 1
                    return seen[0] == 1
                return True
            plan = {**plan, "lived_in": [({**x, "count": 1} if x.get("category") == "basket" and x.get("on") == "floor" else x)
                                         for x in plan.get("lived_in", []) if keep(x)]}   # one entry with count 4 slipped through (shop r4)
        if self.doc.get("type") == "pharmacy":                 # one dispensing counter (shop r11: a planned row of 3 desks with monitors read
            plan = {**plan, "furniture": [({**f, "count": 1} if f["category"] == "reception_desk" else f)   # as an office, 3 of 3)
                                          for f in plan.get("furniture", [])]}
        if self.doc.get("type") == "pharmacy":                 # the dispensing counter stands 1 m in front of the medicine wall, facing the
            shelves = [f["id"] for f in plan.get("furniture", []) if f["category"] == "backbar_shelf"]   # room (shop r9: 'a reception desk
            if shelves:                                                                                  # mid-floor, not a dispensary')
                plan = {**plan, "furniture": [({**f, "relation": "in_front_of", "target": shelves[0], "gap_m": 1.0, "face_away": True}
                                               if f["category"] == "reception_desk" else f) for f in plan["furniture"]]}
        if self.doc.get("type") == "pharmacy":                 # dispensing counter and medicine wall on walls, no office chair on the floor
            plan = {**plan, "furniture": [({**f, "relation": "against_wall", "target": None}            # (shop r3: a desk + swivel chair
                                           if f["category"] == "backbar_shelf" or (f["category"] == "reception_desk" and not f.get("face_away")) else f)   # mid-floor, back shelves stood
                                          for f in plan.get("furniture", []) if f["category"] != "desk_chair"]}   # 'beside' as an A-frame)
        if self.doc.get("type") in ("exam-room", "physio-room") and self.doc.get("area_m2", 99) < 14:   # 11 -> 14: a 12 m2 treatment
            # room's curtain and its posts cut the room in two (floor F3 r16: layout 5, 3 of 3)   # no privacy curtain in a 9 m2
            plan = {**plan, "furniture": [f for f in plan.get("furniture", []) if f["category"] != "privacy_curtain"]}   # room: its track
            # crossed the room and filled 2 of 4 wides (floor F3 r6-r11)
            plan = {**plan, "furniture": [f for f in plan["furniture"] if f["category"] != "conference_chair"]}   # nor a guest chair: the
            # desk, two chairs, sink run and couch jammed within a metre (floor F3 r19: office_0-4 layout 5, 3 of 3)
        if self.doc.get("type") == "clinic-reception":         # one reception counter (floor E3 r11: 'a stray duplicate counter', 3 of 3)
            seen_rd, fs_ = [0], []
            for f in plan.get("furniture", []):
                if f["category"] == "reception_desk":
                    seen_rd[0] += 1
                    if seen_rd[0] > 1:
                        continue
                    f = {**f, "count": 1}
                fs_.append(f)
            plan = {**plan, "furniture": fs_}
        if self.doc.get("type") == "clinic-reception":         # a staff side: binders on shelving behind the desk ('the desk floats as an
            rd_ = next((f["id"] for f in plan.get("furniture", []) if f["category"] == "reception_desk"), None)   # island, nothing
            if rd_:                                                                                              # behind it', D3 r17, 3/3)
                plan = {**plan, "furniture": plan["furniture"] + [{"id": "rec_back", "category": "office_bookcase", "relation": "against_wall",
                                                                   "near_to": rd_, "forced": True}],   # the nearest wall: 'behind' at
                        # 0.95 m ran into the wall the desk keeps 1.2 m off (floor D3 r19: not placed, 'a desk floating mid-room', 3 of 3)
                        "lived_in": plan.get("lived_in", []) + [{"category": "book_stack", "on": "rec_back", "fill": True}]}
        if self.doc.get("type") == "clinic-reception":         # no staff filing on the patient side: a cabinet between the benches read as
            plan = {**plan, "furniture": [f for f in plan.get("furniture", []) if f["category"] != "filing_cabinet"]}   # 'staff furniture
            # in a patient area' (floors E3 r14, D3 r16, F3 r15, 3 of 3 each)
        if self.doc.get("type") in ("convenience", "grocery"):  # free-standing gondolas from the fill only: parallel runs, 1.2 m aisles --
            plan = {**plan, "furniture": [f for f in plan.get("furniture", []) if f["category"] != "gondola"]}   # the planned ones stood
            # 'at mixed angles like cubby bookcases, no clean aisles' (floor I r25, 3 of 3)
        if self.doc.get("type") == "exam-room":                # a patient chair beside the GP's desk (floor D3 r9-r11: 'no patient chair
            fs_ = plan.get("furniture", [])                     # beside the desk', 3 of 3)
            dk = next((f["id"] for f in fs_ if f["category"] == "clinic_desk"), None)
            if dk and not any(f["category"] == "conference_chair" for f in fs_):
                plan = {**plan, "furniture": fs_ + [{"id": "patient_chair", "category": "conference_chair", "relation": "beside", "target": dk}]}
        if self.doc.get("type") == "cafe":                     # a window bar is a wall ledge: planned as a 'row' it stood mid-aisle as
            plan = {**plan, "furniture": [({**f, "relation": "near_window", "target": None} if f["category"] == "window_bar" else f)   # a
                                          for f in plan.get("furniture", [])]}   # poseur table (floor H r21: dining layout 5, 3 of 3)
            wb = next((f["id"] for f in plan["furniture"] if f["category"] == "window_bar"), None)
            if wb:                                               # and its stools sit at it, not in a free row
                plan = {**plan, "furniture": [({**f, "relation": "in_front_of", "target": wb} if f["category"] == "bar_stool"
                                               and f.get("relation") in ("row", "center", "corner") else f) for f in plan["furniture"]]}
        if self.doc.get("type") == "cafe":                     # tables by floor area: rows of 4 x 5 filled a 93 m2 hall 'wall to wall'
            room_t = self._cafe_table_cap()                     # (floor G r10-r12, layout 5, 9 of 9 calls)
            keep = []
            for f in plan.get("furniture", []):
                if f["category"] == "cafe_table":
                    k = min(f.get("count", 1), room_t); room_t -= k
                    if k <= 0:
                        continue
                    f = {**f, "count": k}
                keep.append(f)
            plan = {**plan, "furniture": keep}
        from room_planner import proc_assets as _pa0
        back_staff = str(self.doc.get("id", "")).startswith("kitchen") or \
            any(v in ("convenience", "grocery", "warehouse") for v in getattr(_pa0, "FLOOR_VENUES", ()))   # a shop / warehouse floor's
        # staff room too (floor I r15: 'no lockers, a generic kitchenette', 3 of 3)
        if self.doc.get("type") == "break-room" and self.doc.get("area_m2", 99) < 20 and back_staff and not plan.get("fixed"):     # no staff lockers into a fixed commercial kitchen
            # a back staff room (a floor's kitchen_ room) only: an office pantry lost its table to the lockers (floor C r7) (floors G/H r11-12:
            fs_ = plan.get("furniture", [])                                              # 'no lockers, nothing says staff', 3 of 3)
            self.staff_hooks = self.doc.get("area_m2", 99) < 16   # coat hooks + notice + clock on its walls as well (no-locker staff rooms
            # read 'no lockers, under-furnished', comp 5-6, floor G r26 -- so the lockers stay, placed FIRST as in G r18, the best staff
            # room: placed after the table they found only a wall against its edge)
            # (floors G r20-r25, H r24-r26: 'the table jammed against the locker fronts' whatever the order): coat hooks + a notice on the
            # wall instead (critics asked for 'lockers, coat hooks or a notice board')
            if not any(f["category"] == "locker" for f in fs_):
                run_ = next((f["id"] for f in fs_ if f["category"] == "pantry_run"), None)
                small_ = 12 <= self.doc.get("area_m2", 0) < 16
                lk = {"id": "staff_lockers", "category": "locker", "relation": "against_wall",   # off the glazing (G r33: 'lockers over the
                      "avoid_windows": self.doc.get("area_m2", 0) >= 15 or small_, **({"away_from": run_} if run_ else {})}   # window')   # a small room: the round table set first, lockers after it (G r30-r32:
                plan = {**plan, "furniture": fs_ + [lk] if small_ else [lk] + fs_}   # lockers first left the table only a wall and one chair)
                # otherwise lockers first: after the table set, placed first, their 0.8 m
                # clearance plus the run's strip left the table no floor (floors G r20, I r16: 'no table, no chairs', 3 of 3)
                # (avoid_windows put them opposite the run:
                                               # with their clearance and the run's strip the staff table found no floor, G r20)   # before the table: it was set
                # against the locker fronts (floor H r13, 3 of 3)
            plan = {**plan, "lived_in": [x for x in plan.get("lived_in", []) if x.get("category") != "wine_bottle"]}   # (floor G r11)
            from room_planner import proc_assets as _pa
            # (no prep station: in a 14-16 m2 staff room it took the staff table's floor -- floors G r19 / H r21: 'nowhere to sit',
            # kitchen fn 5 / comp 4; the room is a staff room, as G's passing one is)
        if self.doc.get("type") == "break-room" and self.doc.get("area_m2", 0) >= 20 and not str(self.doc.get("id", "")).startswith("kitchen") and not proc_assets_kit().STYLE.get("no_break_tables"):
            fs_ = plan.get("furniture", [])                     # a crew room seats a crew: a second table set (floor J r13: 'one high
            if sum(f.get("count", 1) for f in fs_ if f["category"] == "break_table") < 2:   # table, half the room bare', comp 6, 3 of 3)
                plan = {**plan, "furniture": fs_ + [{"id": "table_2", "category": "break_table", "relation": "center"},
                                                    {"id": "chairs_2", "category": "break_chair", "relation": "around", "target": "table_2", "count": 4}]}
        if self.doc.get("type") == "break-room" and self.doc.get("area_m2", 99) >= 12:   # the staff table is dining height there: the
            bt = {f["id"] for f in plan.get("furniture", []) if f["category"] == "break_table"}   # plan's bar stools round it sat 'above
            plan = {**plan, "furniture": [({**f, "category": "break_chair"} if f["category"] == "bar_stool" and f.get("target") in bt else f)
                                          for f in plan.get("furniture", [])]}   # the tabletop' (floor G r23, 3 of 3)
        if self.doc.get("type") == "break-room":               # snack tubs/boxes read as office stock anywhere in a pantry: 'a desk file
            plan = {**plan, "lived_in": [x for x in plan.get("lived_in", []) if x.get("category") not in ("snack", "snack_basket")]}
            # organiser with folders', 'binders on the counter' (floor C r10), 'retail stock' (I r9), 'a crate centrepiece' (G r9)
        if self.doc.get("type") == "break-room":               # a staff table holds a few things, not a drinks display (floor J r5: 6-10
            tabs = {f["id"] for f in plan.get("furniture", []) if f["category"] in ("break_table", "cafe_table", "window_bar")}   # cans per table)
            n_on, kept = {}, []
            for x in plan.get("lived_in", []):
                h = x.get("on")
                if h in tabs:
                    if x.get("category") in ("drink_cans", "bottle", "wine_bottle", "snack_basket", "storage_bin", "snack", "book_stack",
                                             "paper_stack", "open_book", "notebook", "fruit_bowl"):   # snack tubs; books/binders (H r15)
                        # read as 'retail stock dumped on the staff table' (floor I r9, 3 of 3)   # crates of colour read
                                                                                                                     # as files (floor D3 r7)
                        continue
                    k = min(x.get("count", 1), 3 - n_on.get(h, 0))
                    if k <= 0:
                        continue
                    n_on[h] = n_on.get(h, 0) + k; x = {**x, "count": k}
                kept.append(x)
            plan = {**plan, "lived_in": kept}
        if self.doc.get("type") in ("convenience", "grocery", "pharmacy", "boutique"):   # no loose basket on a sales floor (floor I r5:
            plan = {**plan, "lived_in": [x for x in plan.get("lived_in", [])            # 'a dark box dropped in the aisle', 3 of 3)
                                         if not (x.get("category") == "basket" and x.get("on") == "floor")]}
        if self.doc.get("type") in ("convenience", "grocery"):   # coolers back onto a wall (floor I r3: a cooler group 'beside' the
            plan = {**plan, "furniture": [({**f, "relation": "against_wall", "target": None}       # first stood mid-floor, black back
                                           if f["category"] == "beverage_fridge" and f.get("relation") not in ("row", "against_wall") else f)   # to the aisle)
                                          for f in plan.get("furniture", [])]}
        if self.doc.get("type") == "boutique":                 # booths stand with their back to a wall (shop r2: 'a blank slab mid-floor')
            plan = {**plan, "furniture": [({**f, "relation": "against_wall", "target": None} if f["category"] == "fitting_room" else f)
                                          for f in plan.get("furniture", [])]}
        if self.doc.get("type") == "break-room":               # a pantry table is a counter along the window, not a dining table mid-room
            big = self.doc.get("area_m2", 0) >= 12                # -- in a small pantry; a 14 m2 staff room's table at the window read as a
            plan = {**plan, "furniture": [({**f, "relation": "center" if big else "near_window" if self.doc.get("windows") else "against_wall",
                                            "target": None}       # ledge with stools (floor G r7, 3 of 3): it stands mid-room
                                           if f["category"] == "break_table" else f) for f in plan.get("furniture", [])]}
        if self.doc.get("type") in catalog.WORK_ROOMS:          # cabinets back onto a wall (floor F r2: a filing cabinet 'beside' the
            plan = {**plan, "furniture": [({**f, "relation": "against_wall", "target": None}   # first stood mid-floor inside the door, 3/3)
                                           if f["category"] == "filing_cabinet" and f.get("relation") != "against_wall" else f)
                                          for f in plan.get("furniture", [])]}
        from room_planner import proc_assets as _pa
        own = not plan.get("fixed") and (not _pa.STYLE.get("venue") or not _pa.VENUE or _pa.VENUE == _pa.STYLE["venue"])
        for req in _pa.STYLE.get("require", []) if own else []:  # a style's signature piece (chain cafe: the banquette), only in the kit's
            if not any(f["category"] == req["category"] for f in plan.get("furniture", [])):
                plan = {**plan, "furniture": plan.get("furniture", []) + [dict(req)]}
                _log(f"style requires {req['category']}: added")
        if self.doc.get("type") == "office":                   # a clinic floor's manager office planned in clinic words keeps its desk
            plan = {**plan, "furniture": [({**f, "category": "office_desk"} if f["category"] == "clinic_desk" else f)   # (floor E3 r8:
                                          for f in plan.get("furniture", [])]}   # clinic_desk dropped as off-vocabulary, its chairs stood alone)
        if not plan.get("fixed"):                               # a fixed fit-out names its own categories (floor E3 r2: the clinic utility's
            plan = self._in_vocab(plan)                         # medical_cabinet was 'off-vocabulary for utility' -- an empty steri room)
        if self.doc.get("type") == "office":                   # a private office's guest chairs face the desk as a pair; a second chair
            fs = plan.get("furniture", [])                      # 'beside' the first floated mid-room (floor B r5, 3 of 3), and a
            g = [f for f in fs if f["category"] == "conference_chair"]   # whiteboard in every office cloned the rooms
            desk = next((f["id"] for f in fs if f["category"] in ("office_desk", "clinic_desk")), None)
            if desk:                                             # always one guest at least: 'no visitor chair facing the desk' in
                fs = [f for f in fs if f["category"] != "conference_chair"] + \
                     [{**(g[0] if g else {"id": "guest_x"}), "category": "conference_chair", "relation": "in_front_of", "target": desk, "gap_m": 0.3,   # at the default
                       # gap the guest stood ~1 m off the desk, mid-room (floor J r25: 'the chair floats', 3 of 3)
                       "count": min(2, sum(f.get("count", 1) for f in g)) if g else 1}]   # every floor's offices (J r24, C r14, A2 r13, 3 of 3)
            # one task chair, at the desk: chairs aimed at a dropped cabinet stood mid-floor (floor E3 r8: '4 lab stools, none at the desk')
            dc = [f for f in fs if f["category"] == "desk_chair"]
            fs = [f for f in fs if f["category"] != "desk_chair"]
            fs = [({**f, "relation": "against_wall", "gap_m": 1.05, "target": None} if f["id"] == desk else f) for f in fs]   # 1.05: at 0.9 a 0.65 m task chair 0.25 m behind touched the wall and never placed (floor D3 r16-r18); the chair
            # sits between desk and wall, guests face it from the room (floor F3 r8: 'two task chairs side by side at one desk', 3/3)
            if desk:
                k_ = next(i for i, f in enumerate(fs) if f["id"] == desk) + 1   # right after its desk: the guests placed first took the
                # front and the task chair found no spot (floor D3 r19: 'no chair at the manager's desk', completeness 4-5, 3 of 3)
                fs.insert(k_, {**(dc[0] if dc else {"id": "desk_chair_x"}), "category": "desk_chair", "relation": "behind", "target": desk,
                               "count": 1})
                clinic_fl = any(v in ("clinic-reception", "exam-room", "dental-room", "physio-room") for v in getattr(_pa, "FLOOR_VENUES", ()))
                if self.doc.get("area_m2", 0) >= 20 and not clinic_fl and sum(f.get("count", 1) for f in fs if f["category"] == "office_desk") < 2:
                    # not a clinic's practice manager: two desks read as 'a shared two-person office' (floor D3 r16, 3 of 3)
                    # a big office is a shared one: a second workstation (floor J r12: one desk in 27 m2, 'half empty', 3 of 3)
                    fs += [{"id": "desk_2", "category": "office_desk", "relation": "against_wall", "gap_m": 1.05, "away_from": desk},
                           {"id": "desk_chair_2", "category": "desk_chair", "relation": "behind", "target": "desk_2", "count": 1}]
                elif self.doc.get("area_m2", 0) >= 18 and not clinic_fl:   # (a clinic's: no café pedestal table -- 'a café corner,
                    # not a clinic office', floor D3 r22, 3 of 3)
                    # a manager's office keeps one desk, and its other half a small round meeting table with two chairs ('half the room
                    # empty, everything at one end', floor F3 r16-r17, 3 of 3)
                    fs += [{"id": "office_mt", "category": "meeting_table", "relation": "center", "away_from": desk, "forced": True},   # an
                           # office-family 1.2 m table: the café pedestal table 'butted against the desk' read as 'café furniture' (floor B r11, 3 of 3)
                           {"id": "office_mt_c", "category": "conference_chair", "relation": "around", "target": "office_mt", "count": 2,
                            "forced": True}]   # office chairs: café chairs read as 'a dining set' (floor E3 r17, 3 of 3)
            if self.rng.random() < 0.5:
                fs = [f for f in fs if f["category"] != "whiteboard"]
            fs = [({**f, "category": "office_bookcase"} if f["category"] == "bookshelf" else f) for f in fs]
            plan = {**plan, "lived_in": plan.get("lived_in", []) + [{"category": "book_stack", "on": f["id"], "fill": True}
                                                                    for f in fs if f["category"] == "office_bookcase"]}
            fs = [({**f, "relation": "against_wall", "target": None, "near_to": desk} if f["category"] == "office_bookcase" and desk else f)
                  for f in fs]                                   # by the desk, not inside the door swing (floor F3 r7, 3 of 3)
            if self.doc.get("area_m2", 99) < 16 or getattr(_pa, "FLOOR_VENUES", ()):   # no floor tree in a small office (it stood in the
                # entry, F3 r7), none on floor scenes ('a domestic olive tree crowds the desk', J r14, 3 of 3)
                fs = [f for f in fs if f["category"] != "floor_plant"]
            if desk and not any(f["category"] in ("bookshelf", "office_bookcase") for f in fs) and "office_bookcase" not in plan.get("forbid", ()):   # a private office keeps its binders (unless the kit forbids bookcases: B r20)
                fs.append({"id": "books", "category": "office_bookcase", "relation": "against_wall", "near_to": desk})   # (floor A r3)
                plan = {**plan, "lived_in": plan.get("lived_in", []) + [{"category": "book_stack", "on": "books", "fill": True}]}
            if plan.get("forbid"):                               # the kit's forbid list also binds this office block's own auto-adds (office_mt table + chairs, binders)
                _bad = set(plan["forbid"])
                _gone = {f["id"] for f in fs if f["category"] in _bad or (f.get("id", "").startswith("office_mt") and ("meeting_table" in _bad or "conference_chair" in _bad))}
                fs = [f for f in fs if f["id"] not in _gone]
                plan = {**plan, "lived_in": [l_ for l_ in plan.get("lived_in", []) if l_.get("on") not in _gone]}
            plan = {**plan, "furniture": fs}
        items = plan.get("furniture", [])
        first = sorted((f for f in items if f["category"] in self.FIRST), key=lambda f: self.FIRST.index(f["category"]))
        # the sink run before the desk: a desk + curtain took its wall (floor D3 r13: office_0-5 'no basin', 3 of 3)
        rest = [f for f in items if f["category"] not in self.FIRST]
        rest.sort(key=lambda f: f["category"] in ("ladder", "utility_cart", "step_stool"))   # shelving before the loose kit: a ladder and a
        # cart took the wall a stockroom's second shelf needed (floor G r26: 'one rack', completeness 5, 3 of 3)
        if self.doc.get("type") == "open-office":               # pods are laid out as a grid, not per planned relation
            rest = [f for f in rest if f["category"] != "workstation_pod"]
            failed = self.place_all(first)
            self._pod_grid()
            # a storage run on the perimeter: 'a third of the floor an empty band, no storage, lockers or printer' (floor C r9-r11, 3 of 3)
            self.furniture({"id": "oo_files", "category": "filing_cabinet", "relation": "against_wall", "count": 3})
            self.furniture({"id": "oo_books", "category": "office_bookcase", "relation": "against_wall", "count": 2})
            self.lived_in({"category": "book_stack", "on": "oo_books", "fill": True})
            failed += self.place_all(rest)
        else:
            failed = self.place_all(first + rest)
        # a fixed service-room fit-out is final: the LLM revision turned a restroom into a packing bay (floor J: +11 benches, racks, a plant)
        hall = self.doc.get("type") == "warehouse" and self.doc.get("area_m2", 0) >= 120   # the aisle pass owns a hall's floor: the
        # revision's 6 extra racks stood 'loose at mixed angles mid-hall' (floor J r10: layout 7 -> 5, 3 of 3)
        rep = self.report(plan, failed) if self.revise is not None and not plan.get("fixed") and not hall else None
        if rep is not None and (failed or any(r["area_m2"] >= 4 for r in rep["empty_floor"])):
            _log(f"report: not placed {[x['category'] for x in rep['not_placed']]}, empty {[r['area_m2'] for r in rep['empty_floor']]} m2")
            new = self.revise(plan, rep)
            if new:
                new = self._in_vocab(new)
                _dm = ({"display_table", "clothing_rack", "fitting_room", "wall_gondola", "mirror", "counter", "armchair", "rug"} if MUSEUM else
                       {"waiting_bench", "reception_desk", "desk_chair", "filing_cabinet", "sofa", "armchair", "coffee_table", "rug", "floor_plant"}
                       if (CLINIC_LOBBY and self.doc.get("type") == "clinic-reception") else set())
                if _dm:                                          # the LLM revision re-adds what the mode's layout already owns (museum r7: a clothing rack in the strip)
                    new = {**new, "furniture": [f for f in new.get("furniture", []) if f["category"] not in _dm]}
                if self.doc.get("type") == "open-office":       # the grid owns the pods
                    new = {**new, "furniture": [f for f in new.get("furniture", []) if f["category"] != "workstation_pod"]}
                if self.doc.get("type") == "warehouse":
                    new = self._warehouse_plan(new, have=sum(rd._factory(v[0].name) == "WorkbenchFactory" for v in self.ids.values()))
                if self.doc.get("type") in ("clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy"):
                    new = {**new, "furniture": [f for f in new.get("furniture", []) if f["category"] not in ("floor_plant", "privacy_curtain")]}
                    # the revision re-added plants the cap removed (r8) and stood failed curtains on far walls (r15: 'a curtain that screens nothing')
                    # re-added the plants the plan cap removed (clinic r8: 4 plants in physio)
                if self.doc.get("type") == "cafe":              # the revision filled the hall back up past the cap (floor G r12: tblD, tblE)
                    have_t = sum(rd._factory(v[0].name) == "CafeTableFactory" for v in self.ids.values())
                    room_t = max(0, self._cafe_table_cap() - have_t)
                    keep = []
                    for f in new.get("furniture", []):
                        if f["category"] == "cafe_table":
                            k = min(f.get("count", 1), room_t); room_t -= k
                            if k <= 0:
                                continue
                            f = {**f, "count": k}
                        keep.append(f)
                    new = {**new, "furniture": keep}
                if plan.get("forbid"):                                  # the kit's forbid list also binds the REVISION (B r18: the LLM revision re-added a central table + bookcase after the first strip)
                    new = {**new, "furniture": [f for f in new.get("furniture", []) if f["category"] not in plan["forbid"]]}
                before = len(self.ids)
                failed = self.place_all(new.get("furniture", []))
                self.stats["revised_rooms"] = self.stats.get("revised_rooms", 0) + 1
                self.stats["revise_added"] = self.stats.get("revise_added", 0) + len(self.ids) - before
                # lived_in: the first plan's and the revision's together -- the revision's list targeted its own new racks, none placed,
                # and replacing the first list left every rack bare (wh r23)
                seen = {(x.get("category"), x.get("on")) for x in plan.get("lived_in", [])}
                plan = {**plan, "adjust": new.get("adjust", plan.get("adjust", [])),
                        "lived_in": plan.get("lived_in", []) + [x for x in new.get("lived_in", []) if (x.get("category"), x.get("on")) not in seen]}
                _log(f"revised: +{len(self.ids) - before} furniture, still not placed {[it['category'] for it, _ in failed]}")
        self.drop_spares()
        self.fill_empty(plan)
        for hid, (o_, _f) in list(self.ids.items()):             # every bookcase carries books (P2 r1 CNT-04: an empty freestanding shelf in a bedroom)
            if "ookcase" in rd._factory(o_.name) and ":" not in hid and not any(k.startswith(f"{hid}:") for k in self.ids):
                try:
                    self.fill({"on": hid, "category": "book_stack"}, _cls(catalog.LIVED_IN["book_stack"]["src"]))
                except Exception as ex:                          # noqa: BLE001 -- books are an extra
                    _log(f"bookcase fill {hid}: {ex!r}"[:120])
        if self.doc.get("type") == "break-room" and proc_assets_kit().STYLE.get("lobby_stair") and not any(rd._factory(v[0].name) == "StairFlightFactory" for v in self.ids.values()):
            self._lobby_stair(plan)                              # N2 lobby: the wall / corner placements found no 1.3 x 3.6 m footprint (r11, r12): a free-floor spot
        if self.doc.get("type") == "break-room" and not any("Table" in rd._factory(v[0].name) or "table" in rd._factory(v[0].name) for v in self.ids.values()) and not proc_assets_kit().STYLE.get("no_break_tables"):      # a kit that forbids break tables (N2 lobby) gets none from the fallback either
            self._fill_tables(plan, "break_table", "break_chair", 2.5)   # a staff room with chairs but no table (floor C r23 LAY-02: one lone chair)
        if self.doc.get("type") == "cafe":
            self._drop_orphan_chairs()
            self._table_guard(False)                             # every standard table keeps >= 2 chairs or goes (S6 r9: bare tables by the pillar)
            self._drop_orphan_chairs()                           # again: a table the guard just removed leaves its ring of chairs (S7 r11: chairs at (4.0,3.5), (4.9,2.6), (5.8,3.5) around a missing table)
            self._pair_chairs()                                  # and every chair faces its table
        elif self.doc.get("type") == "dining-room":
            self._drop_orphan_dining_chairs()
        elif self.doc.get("type") == "break-room":
            self._pair_chairs()                                  # floors G / H café rooms: chairs turned to their tables
        if os.environ.get("ROOM_DESK_RETRY") == "1" and self.doc.get("type") == "office":      # O4 r4 F3: a small private office kept its bookcase and lost the desk + chair -> retry both compact, desk on a wall
            fd = [x for x in failed if x[0]["category"] in ("office_desk", "desk_chair")]
            if any(x[0]["category"] == "office_desk" for x in fd):
                from room_planner import proc_assets as _pa_d
                _pa_d.OfficeDeskFactory.COMPACT = True
                for it, _f in sorted(fd, key=lambda x: x[0]["category"] != "office_desk"):
                    rel = {**it, "relation": "against_wall", "target": None, "wall": None} if it["category"] == "office_desk" else it
                    if self.place_all([rel]) and it["category"] == "office_desk":      # still no room (O4 r6 office_0/5, 10.6 m2): the desk outranks the plant, the whiteboard and the filing cabinet -> clear those one by one and retry
                        for cat_ in ("floor_plant", "whiteboard", "filing_cabinet"):
                            gone_ = False
                            for f_ in plan.get("furniture", []):
                                if f_["category"] == cat_ and f_["id"] in self.ids:
                                    o_x = self.ids.pop(f_["id"])[0]; fp_ = fr.footprint(o_x)[:4]
                                    self.obstacles[:] = [b_ for b_ in self.obstacles if not all(abs(b_[i_] - fp_[i_]) < 0.1 for i_ in range(4))]          # its footprint box is freed too
                                    bpy.data.objects.remove(o_x, do_unlink=True); gone_ = True
                            if gone_:
                                bpy.context.view_layer.update()
                                if not self.place_all([rel]):
                                    break
                    if not [x for x in [rel] if x["id"] not in self.ids]:
                        failed = [x for x in failed if x[0] is not it]
        if os.environ.get("ROOM_RESTROOM_FIX") == "1" and self.doc.get("type") == "restroom":     # O3 r3 / O4 r4 F1: the 2.6 m vanity found no wall in a 11-13 m2 room -> every restroom still gets its own basin + mirror, smaller ones first; the first restroom is the men's: a urinal run
            for it, _f in list(failed):
                if it["category"] == "oak_vanity_long":
                    for sub in ("oak_vanity", "wash_basin"):
                        if not self.place_all([{**it, "category": sub, "count": 1}]):
                            failed = [x for x in failed if x[0] is not it]; break
            if str(self.doc.get("id", "")).endswith("/0") and not any(rd._factory(v[0].name) == "UrinalFactory" for v in self.ids.values()):
                self.place_all([{"id": "uri_fix", "category": "urinal", "relation": "against_wall", "count": 1}])
        for it, _ in failed:
            self.stats["plan_dropped"][it["category"]] = self.stats["plan_dropped"].get(it["category"], 0) + 1
        for it in plan.get("adjust", []):
            self.adjust(it)
        self.toss = []
        for hid_ in getattr(self, "mode_dress", []):              # the casual cafe tables stood bare (S29F r7 D8) -> two mugs, a plate and a candle on each
            for cat_, n_ in (("mug", 2), ("plate", 1), ("candle", 1)):
                try:
                    self.lived_in({"category": cat_, "on": hid_, "count": n_, "pose": "placed"})
                except Exception as ex_:                         # noqa: BLE001 -- dressing is an extra
                    _log(f"lounge dress {cat_}: {ex_!r}"[:100])
        for it in plan.get("lived_in", []):
            self.lived_in(it)
        if self.doc.get("type") in ("convenience", "boutique", "grocery"):   # the checkout has its register
            for hid, (o_, _) in list(self.ids.items()):
                if rd._factory(o_.name) in ("CafeCounterFactory", "CheckoutCounterFactory"):   # a shop's till is the checkout
                    # factory: matching the café counter only left it with a monitor and nothing else (floor I r22: use 6, 3 of 3)
                    self.lived_in({"category": "register", "on": hid})
                    self.lived_in({"category": "basket", "on": hid})
                    break
        if self.doc.get("type") == "cafe":
            self._table_guard(True)                              # and every kept table carries something (cups / plate / vase)
        if proc_assets_kit().STYLE.get("window_curtains") and self.doc.get("type") in proc_assets_kit().STYLE["window_curtains"]:
            self._window_curtains()                              # kit window_curtains=[room types]: a gathered sheer pair on every window span, fixed (not searched for)
        fp_ = (proc_assets_kit().STYLE.get("forced_plants") or {}).get(self.doc.get("type"))
        if fp_:
            self._forced_plants(int(fp_))                        # kit forced_plants={room type: n}: floor plants at corners / along the walls whatever the planner's relations found (H r67: 3 of 4 dropped)
        self.desk_clutter()
        if os.environ.get("ROOM_DOOR_SIGNS") == "1" and self.doc.get("type") == "hallway":
            self._door_signs()
        self.traces(plan)
        self.appliance_finish()
        settle(self.toss, self.room, self.rng, self.stats)

    def _table_guard(self, ware):
        """ware=False: each CafeTableFactory table gets chairs around it until it has 2 within 1.1 m; a table that cannot get 2 chairs is removed. ware=True: a table with nothing on it gets
        a mug / plate / takeaway cup / bud vase."""
        tabs = [(hid, v[0]) for hid, v in self.ids.items() if rd._factory(v[0].name) == "CafeTableFactory"]
        seats = lambda: [v[0] for v in self.ids.values() if any(k in rd._factory(v[0].name) for k in ("Chair", "Stool", "chair", "stool"))]
        removed = added = 0
        for hid, t in tabs:
            c = t.matrix_world.translation
            if not ware:
                near = lambda: sum(1 for q in seats() if (q.matrix_world.translation.x - c.x) ** 2 + (q.matrix_world.translation.y - c.y) ** 2 < 1.21)
                n0 = near(); r_ = max(t.dimensions[0], t.dimensions[1]) / 2
                for k in range(8):
                    if near() >= 2:
                        break
                    a = k * math.pi / 4 + self.rng.uniform(-0.2, 0.2)
                    o, front = self._make("cafe_chair")
                    if o is None:
                        break
                    bpy.context.view_layer.update()
                    x, y = c.x + (r_ + 0.3) * math.cos(a), c.y + (r_ + 0.3) * math.sin(a)
                    if fr._place(o, x, y, a + math.pi, self.room, self.obstacles, front):
                        self.ids[f"{hid}_g{k}"] = (o, front); self.stats["furniture_added"] += 1; added += 1
                    else:
                        bpy.data.objects.remove(o, do_unlink=True)
                if near() < 2:
                    for k2 in [k_ for k_, v in self.ids.items() if k_.startswith(f"{hid}_g")]:
                        bpy.data.objects.remove(self.ids.pop(k2)[0], do_unlink=True)
                    bpy.data.objects.remove(t, do_unlink=True); self.ids.pop(hid, None); removed += 1
            else:
                zt = c.z + t.dimensions[2] / 2
                has = any(o.name != t.name and abs(o.matrix_world.translation.x - c.x) < 0.4 and abs(o.matrix_world.translation.y - c.y) < 0.4 and zt - 0.25 < o.matrix_world.translation.z < zt + 0.4
                          and not any(k in o.name for k in ("Chair", "Stool")) for o in bpy.data.objects if o.type == "MESH")
                if not has:
                    self.lived_in({"category": self.rng.choice(("mug", "plate", "takeaway_cup", "bud_vase")), "on": hid}); added += 1
        self.stats["table_guard" + ("_ware" if ware else "")] = {"added": added, "tables_removed": removed}

    def _table_ware_all(self):
        """A table setting (plate + glass) and a candle on every table-like object that has nothing on its top."""
        pa = proc_assets_kit(); n = 0
        for hid, (t, _f) in list(self.ids.items()):
            if "Table" not in rd._factory(t.name) and "Bar" not in rd._factory(t.name):
                continue
            bb = [t.matrix_world @ Vector(c) for c in t.bound_box]
            top = max(p.z for p in bb); cx, cy = (min(p.x for p in bb) + max(p.x for p in bb)) / 2, (min(p.y for p in bb) + max(p.y for p in bb)) / 2
            if top < 0.6 or top > 1.25 or max(max(p.x for p in bb) - min(p.x for p in bb), max(p.y for p in bb) - min(p.y for p in bb)) > 2.0:
                continue                                         # a counter or a floor object, not a table
            if any(o.type == "MESH" and o is not t and abs(o.matrix_world.translation.x - cx) < 0.4 and abs(o.matrix_world.translation.y - cy) < 0.4
                   and top - 0.05 < o.matrix_world.translation.z < top + 0.35 and not any(k in o.name for k in ("Chair", "Stool", "Table")) for o in bpy.data.objects):
                continue
            o, _fr = self._make("rt_setting")
            if o is not None:
                o.rotation_mode = "XYZ"; o.rotation_euler = (0, 0, self.rng.uniform(0, 6.28)); o.location = (cx + self.rng.uniform(-0.08, 0.08), cy + self.rng.uniform(-0.08, 0.08), top + 0.002)
                n += 1
            try:
                cd = pa.TableCandleFactory(self.rng.randrange(1 << 24)).spawn_asset(self.stats["furniture_added"] + n)
                cd.location = (cx + 0.12, cy - 0.1, top + 0.002); n += 1
            except Exception:                                    # noqa: BLE001 -- the candle is an extra
                pass
        self.stats["table_ware_all"] = n
        return n

    def _pair_chairs(self, radius=1.35):
        """Turn every chair / stool that stands within `radius` of a table centre to face that table (S23 r5 LAY-02: a red chair at left-centre faced away from its table)."""
        tabs = [v[0] for v in self.ids.values() if "Table" in rd._factory(v[0].name) or "table" in rd._factory(v[0].name)]
        n = 0
        for hid, (o, front) in list(self.ids.items()):
            f = rd._factory(o.name)
            if not any(k in f for k in ("Chair", "Stool", "chair", "stool")) or not tabs:
                continue
            c = o.matrix_world.translation
            t = min(tabs, key=lambda q: (q.matrix_world.translation.x - c.x) ** 2 + (q.matrix_world.translation.y - c.y) ** 2)
            d = t.matrix_world.translation - c
            if d.x * d.x + d.y * d.y > radius * radius or d.length < 0.05:
                continue
            cur = o.rotation_euler.z + math.atan2(front[1], front[0])          # where the chair's front points now
            want = math.atan2(d.y, d.x)
            diff = (want - cur + math.pi) % (2 * math.pi) - math.pi
            if abs(diff) > 0.35:
                o.rotation_euler.z += diff; n += 1
        bpy.context.view_layer.update()
        self.stats["chairs_paired"] = self.stats.get("chairs_paired", 0) + n
        return n

    BAG_HOSTS = ("OfficeDeskFactory", "ClinicDeskFactory")   # staff desks only: bags by waiting benches read as 'abandoned luggage
    # in the aisles' (floor D3 r14, 3 of 3)

    def appliance_finish(self):
        """Microwaves get an appliance body: the Infinigen factory drew a speckled stone shell that read as 'a granite brick on the
        counter' (floor G r17-r18, staff room coherence 6, 3 of 3)."""
        from room_planner import proc_assets as pa
        body = pa._flat("ir_microwave_body", (0.06, 0.06, 0.065), 0.35, 0.3)
        for o in bpy.data.objects:
            if rd._factory(o.name) != "MicrowaveFactory" or o.parent is not None:
                continue
            for p_ in [o] + list(o.children_recursive):
                for sl in getattr(p_, "material_slots", []):
                    if sl.material and not any(k in sl.material.name.lower() for k in ("glass", "screen", "ir_microwave")):
                        sl.material = body

    def traces(self, plan):
        """Signs of use on work floors: a bag on the floor by every other desk / bench, mats on a gym floor (floors A2-J: 'signs of use'
        median 4-6 in every room that otherwise passed -- a tidy desk reads as unoccupied)."""
        t = self.doc.get("type")
        rid = str(self.doc.get("id", ""))
        ex = (proc_assets_kit().STYLE.get("small_room_extras") or {})                  # kit: everyday floor clutter per room id / type ('lived-in 5', market M r3)
        cats = ex.get(rid) or ex.get("utility" if rid.startswith("utility") else t)
        if cats:
            for n_, c_ in enumerate(cats):                                              # against a wall or in a corner, not mid-floor (M r5: a mop bucket in the room's centre)
                n0 = self.stats["furniture_added"]
                self.furniture({"id": f"extra_{n_}", "category": c_, "relation": "against_wall", "count": 1})
                if self.stats["furniture_added"] == n0:
                    self._fill_items(plan, (c_,), 1.0, limit=1)
        if t not in catalog.WORK_ROOMS or t not in catalog.LIVED_IN["bag"]["rooms"]:
            return
        hosts = [hid for hid, (o_, _) in self.ids.items() if rd._factory(o_.name) in self.BAG_HOSTS]
        if t in ("exam-room", "dental-room", "physio-room", "clinic-reception"):
            hosts = []                                           # a bag on a clinical floor read as 'misplaced clutter' (floor D3 r17)
        for hid in self.rng.sample(hosts, (len(hosts) + 1) // 2):
            self.lived_in({"category": "bag", "on": "floor", "near": hid})
        if t == "physio-room":
            n0 = self.stats["furniture_added"]
            self._fill_items(plan, ("exercise_mat",), 2.0, limit=2)
            if self.stats["furniture_added"] == n0:              # no open region left: mats along a wall (floor F3 r13-r15: '+0', use 3-5)
                self.furniture({"id": "mats_wall", "category": "exercise_mat", "relation": "against_wall", "count": 2})


# ---- physics settle ----------------------------------------------------------------------------------------------------------------
SETTLE_FRAMES = 90
MAX_DRIFT_M = 0.6


PASSIVE_MAX_FACES = 3000


def _proxy(o, kind):
    """A light stand-in for Bullet: the convex hull (a few hundred verts) of an active item, a decimated copy of a passive one.
    Bullet got every vertex (58k-vert mug hull, 500k-face bed) and ran ~8 s per frame on an apartment (2026-10-15)."""
    import bmesh
    if kind == "ACTIVE":
        bm = bmesh.new(); bm.from_mesh(o.data)
        res = bmesh.ops.convex_hull(bm, input=bm.verts)
        bmesh.ops.delete(bm, geom=res["geom_interior"] + res["geom_unused"], context="VERTS")
        me = bpy.data.meshes.new(o.name + ".rbhull"); bm.to_mesh(me); bm.free()
        p = bpy.data.objects.new(o.name + ".rbproxy", me)
    else:
        p = bpy.data.objects.new(o.name + ".rbproxy", o.data)
        n = len(o.data.polygons)
        if n > PASSIVE_MAX_FACES:
            p.modifiers.new("dec", "DECIMATE").ratio = PASSIVE_MAX_FACES / n
    bpy.context.scene.collection.objects.link(p)
    p.matrix_world = o.matrix_world.copy()
    p.hide_render = True
    return p


def _configure(o, kind):
    rb = o.rigid_body
    rb.type = kind
    rb.collision_shape = "MESH" if kind == "PASSIVE" else "CONVEX_HULL"
    rb.mesh_source = "FINAL"                                     # the decimated proxy, not its full base mesh
    rb.friction, rb.restitution, rb.collision_margin = 0.9, 0.0, 0.002
    if kind == "ACTIVE":
        rb.mass, rb.linear_damping, rb.angular_damping = 0.4, 0.5, 0.7


def settle(toss, room, rng, stats):
    """Drop the tossed / leaning items (tilted, a few cm up) onto what is under them with Bullet, keep the settled pose.

    Everything within 1 m of a tossed item (and the room's floor and wall) is a passive collider. An item that drifts more than
    MAX_DRIFT_M, sinks under the floor or ends up non-finite goes back to its upright placement."""
    if not toss:
        return
    stats.setdefault("settled", 0); stats.setdefault("settle_reverted", 0)
    sc = bpy.context.scene
    frame0 = sc.frame_current
    start = {o.name: o.matrix_world.copy() for o, *_ in toss}
    drop = {o.name for o, _, _, d in toss if d}                  # dropped onto a soft host: no upright pose to go back to
    for o, host, pose, _ in toss:                                   # the throw: a tilt, a turn, a few cm of air
        tilt = math.radians(rng.uniform(25, 45) if pose == "leaning" else rng.uniform(15, 70))
        axis = Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), 0)).normalized()
        loc = o.matrix_world.translation.copy()
        if pose == "leaning" and host is not None:               # slide back until it touches the backrest, top falling into it
            back = -(host[0].matrix_world.to_3x3() @ Vector((*host[1], 0))); back.z = 0; back.normalize()
            axis = back.cross(Vector((0, 0, -1))).normalized()
            f = fr.footprint(o)
            half = abs(Vector(((f[1] - f[0]) / 2, (f[3] - f[2]) / 2, 0)).dot(back))
            mid = Vector(((f[0] + f[1]) / 2, (f[2] + f[3]) / 2, (f[4] + f[5]) / 2))
            hit = bpy.context.scene.ray_cast(bpy.context.evaluated_depsgraph_get(), mid + back * (half + 0.005), back, distance=0.6)
            if hit[0]:
                swing = (f[5] - f[4]) / 2 * math.sin(tilt)        # the tilt about the centre swings the top this far back
                loc += back * max(0.0, (hit[1] - mid).dot(back) - half - 0.02 - swing)
        R = Matrix.Rotation(tilt, 4, axis) @ Matrix.Rotation(rng.uniform(-math.pi, math.pi), 4, "Z")
        o.matrix_world = Matrix.Translation(loc + Vector((0, 0, rng.uniform(0.04, 0.12)))) @ R @ o.matrix_world.to_3x3().to_4x4()
    bpy.context.view_layer.update()
    actives = [o for o, *_ in toss]
    boxes = [fr.footprint(o) for o in actives]
    passives = {room.floor.name: room.floor}
    if room.wall is not None:
        passives[room.wall.name] = room.wall
    for t in rd._tops():
        if t in actives or not any(fr._overlap(fr.footprint(t), b, m=0.5) for b in boxes):
            continue
        for x in [t, *t.children_recursive]:
            if x.type == "MESH":
                passives[x.name] = x
    if sc.rigidbody_world is None:
        bpy.ops.rigidbody.world_add()
    rbw = sc.rigidbody_world
    if rbw.collection is None:
        rbw.collection = bpy.data.collections.new("RigidBodyWorld")
    rbw.point_cache.frame_start, rbw.point_cache.frame_end = 1, SETTLE_FRAMES
    # Rigid bodies by collection link, not bpy.ops: an operator per object re-evaluates a whole apartment (minutes per settle).
    proxy = {o.name: _proxy(o, "PASSIVE") for o in passives.values() if o.type == "MESH"}
    proxy.update({o.name: _proxy(o, "ACTIVE") for o in actives if o.type == "MESH"})
    kinds = {proxy[o.name].name: "PASSIVE" for o in passives.values() if o.name in proxy}
    kinds.update({proxy[o.name].name: "ACTIVE" for o in actives if o.name in proxy})
    added = []
    for p in proxy.values():
        rbw.collection.objects.link(p); added.append(p)
    bpy.context.view_layer.update()                              # creates the rigid_body settings of everything linked
    for p in added:
        _configure(p, kinds[p.name])
    rbw.substeps_per_frame, rbw.solver_iterations = 5, 10
    _log(f"settle: {len(actives)} active (hull verts {sum(len(proxy[o.name].data.vertices) for o in actives if o.name in proxy)}), "
         f"{len(added) - len(actives)} passive proxies")
    for f in range(1, SETTLE_FRAMES + 1):
        sc.frame_set(f)
        if f in (1, 10, SETTLE_FRAMES):
            _log(f"settle frame {f}")
    final = {o.name: (proxy[o.name].matrix_world.copy() if o.name in proxy else start[o.name]) for o in actives}
    for p in added:
        rbw.collection.objects.unlink(p)
    coll, rbw.collection = rbw.collection, None
    bpy.data.collections.remove(coll)
    bpy.ops.rigidbody.world_remove()
    sc.frame_set(frame0)
    for p in proxy.values():
        me = p.data if p.data.name.endswith(".rbhull") else None
        bpy.data.objects.remove(p, do_unlink=True)
        if me is not None:
            bpy.data.meshes.remove(me)
    for o in actives:
        m = final[o.name]
        ok = all(math.isfinite(v) for row in m for v in row) and (m.translation.xy - start[o.name].translation.xy).length < MAX_DRIFT_M
        o.matrix_world = m if ok else start[o.name]
        bpy.context.view_layer.update()
        if ok and fr.footprint(o)[4] < room.z - 0.02:            # through the floor
            o.matrix_world, ok = start[o.name], False
        stats["settled" if ok else "settle_reverted"] += 1
        if not ok and o.name in drop:
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update()


SYSTEM_PY = "/root/miniconda3/bin/python3"                       # has the anthropic SDK; Blender's python does not
TOOLS = str(Path(__file__).resolve().parents[1])


def llm_revise(room_doc, seed):
    """(plan, report) -> revised plan via room_planner/revise.py in the system python; None on any failure (keep the first pass)."""
    import subprocess
    import tempfile

    def call(plan, report):
        payload = {k: v for k, v in room_doc.items() if not k.startswith("_")}
        payload["existing"] = [{k: v for k, v in e.items() if not k.startswith("_")} for e in room_doc["existing"]]
        with tempfile.TemporaryDirectory() as d:
            req, out = Path(d) / "req.json", Path(d) / "out.json"
            req.write_text(json.dumps({"room": payload, "plan": plan, "report": report, "seed": seed}))
            r = subprocess.run([SYSTEM_PY, "-m", "room_planner.revise", str(req), str(out)], cwd=TOOLS, capture_output=True,
                               text=True, timeout=600)
            if r.returncode != 0 or not out.is_file():
                _log(f"revise failed ({r.returncode}): {r.stderr[-300:]}")
                return None
            return json.loads(out.read_text())
    return call


def realize(plans, rng, stats, spawn, act, revise=True):
    from room_planner import proc_assets, styles
    proc_assets.STYLE.clear()
    proc_assets.VENUE = plans.get("venue") or ""
    proc_assets.STYLE.update(plans.get("style_spec") or styles.get(plans.get("venue") or "", plans.get("style") or "") or {})
    """plans: plan_scene.py output; act: the activity pass module (supports, put, mark_occupied, corners_of, MAX_Z, tidy)."""
    stats.setdefault("furniture_added", 0); stats.setdefault("plan_dropped", {}); stats["planned_rooms"] = 0; stats.setdefault("adjusted", 0)
    rooms = rd._rooms()
    scene = bpy.context.scene
    obstacles, rugzones = fr.obstacles(rd._tops())
    only_ = {x for x in os.environ.get("ROOM_ONLY", "").split(",") if x}              # incremental round (activity_pass --incremental): realize just these rooms
    for rid, entry in sorted(plans["rooms"].items()):
        if only_ and rid not in only_:
            continue
        parts = rooms.get(rid)
        if not parts or "floor" not in parts:
            continue
        room = fr.Room(rid, parts, scene, bpy.context.evaluated_depsgraph_get())
        before = stats["furniture_added"]
        names_before = {o.name for o in bpy.data.objects}                                # everything this room creates is tagged ir_room=<id> so a later round can remove just that room
        if plans.get("room_venues"):                              # a floor: each room runs its own venue's rules (the scene-wide VENUE
            proc_assets.VENUE = plans["room_venues"].get(rid, "")  # is a single-room-scene notion; user 2026-10-16 floor scenes)
            proc_assets.FLOOR_VENUES = tuple(plans["room_venues"].values())
            proc_assets._ROOM_PICK.clear()                         # one chair / bench / stool model per room, not per floor
        RoomRealizer(entry["room"], room, rng, stats, spawn, act, obstacles, rugzones,
                     float(entry["plan"].get("tidiness", 0.6)),
                     revise=llm_revise(entry["room"], int(plans.get("seed", 0))) if revise else None).run(entry["plan"])
        for o_ in bpy.data.objects:
            if o_.name not in names_before:
                o_["ir_room"] = rid
        stats["planned_rooms"] += 1
        print(f"[plan] {rid}: +{stats['furniture_added'] - before} furniture ({entry['plan'].get('occupant', '')})", flush=True)
    from room_planner import support_check                       # floor furniture hanging over a railing / void: snap onto the floor, or drop it (user 10-23, S34 r16 floating chair); [support] lines
    support_check.apply(stats)


def _install_provenance():
    """Provenance tags for the room realizer's automatic passes (the outermost call wins); see tools/infinigen/provenance.py. A pass is a method; plan-level calls (furniture / lived_in) are tagged plan:*."""
    import functools
    import provenance as pv
    table = {"_coffee_bar": "pass:coffee_bar_zone", "fill_empty": "pass:fill_empty", "_table_guard": "pass:table_guard", "_fill_tables": "pass:fill_tables", "desk_clutter": "pass:desk_clutter",
             "traces": "pass:traces", "_window_curtains": "pass:curtains", "_forced_plants": "pass:plants", "_balloon": "pass:balloons", "_lobby_stair": "pass:lobby_stair", "lived_in": "plan:lived_in"}
    for meth, src in table.items():
        orig = getattr(RoomRealizer, meth, None)
        if orig is None:
            continue

        def mk(orig, src):
            @functools.wraps(orig)
            def w(self, *a, **k):
                with pv.tag(src):
                    return orig(self, *a, **k)
            return w
        setattr(RoomRealizer, meth, mk(orig, src))
    orig_f = RoomRealizer.furniture

    @functools.wraps(orig_f)
    def furn(self, it, *a, **k):
        with pv.tag("pass:required_zone" if str(it.get("id", "")).startswith("req_") else "plan:furniture"):
            return orig_f(self, it, *a, **k)
    RoomRealizer.furniture = furn


_install_provenance()
