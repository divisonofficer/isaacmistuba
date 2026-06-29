"""Multi-level natural-language instruction generation for graph episodes.

Each graph episode can expose a *set* of instructions at different knowledge
levels instead of a single "Go to Goal" string. Generators are deterministic
(template) and grounded; an optional LLM paraphrase layer (see
``instruction_paraphrase``) augments them with more varied English. If no LLM is
available the template instructions stand on their own.

Add a new instruction level by writing a ``gen_*`` function and appending it to
``GENERATORS`` — nothing else needs to change.

An ``Instruction`` is a plain dict::

    {"type": str, "level": str, "text": str, "lang": "en",
     "source": "template"|"codex", "grounding": {...}}
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .object_footprint import footprint_bbox, object_footprint, point_in_footprint

JsonDict = dict[str, Any]
Instruction = dict[str, Any]
XY = tuple[float, float]

# Object categories we are willing to name in instructions; decorative clutter
# (book stacks, trinkets, bowls, bottles, wall art) maps to no noun and is
# skipped automatically because it never appears here.
_DIRECT_TYPE_NOUN = {
    "chair": "chair", "table": "table", "plant": "plant", "shelf": "shelf",
    "bed": "bed", "glass_door": "glass door", "door": "door", "window": "window",
    "mirror_wall": "mirror", "glass_wall": "glass wall",
}
# Infinigen factory keyword → human noun (substring match, lowercased factory).
_FACTORY_NOUN = {
    "bed": "bed", "sofa": "sofa", "couch": "sofa", "chair": "chair", "stool": "stool",
    "diningtable": "dining table", "tabledining": "dining table", "desk": "desk",
    "table": "table", "counter": "counter", "island": "kitchen island",
    "bookcase": "bookcase", "shelf": "shelf", "cabinet": "cabinet",
    "wardrobe": "wardrobe", "dresser": "dresser", "plant": "plant",
    "lamp": "lamp", "toilet": "toilet", "sink": "sink", "bathtub": "bathtub",
    "fridge": "refrigerator", "oven": "oven", "sofa": "sofa",
}
_NEAR_OBJECT_M = 1.6          # a node "is near" an object within this radius
_HAZARD_NEAR_M = 1.4          # mirror/glass "near the path" within this radius
_MAX_TURN_STEPS = 40          # cap turn-by-turn verbosity


def _clean_room_name(raw: str, *, is_label: bool = False) -> str:
    """'bathroom_0/0.floor' -> 'bathroom', 'dining-room_0/1' -> 'dining room',
    label 'Room 1 floor' -> 'room 1'."""
    base = str(raw).split(".")[0]
    if is_label:
        name = re.sub(r"\b(floor|ceiling|region)\b", "", base, flags=re.I)
        return re.sub(r"\s+", " ", name).strip().lower() or "room"
    m = re.match(r"^([A-Za-z][A-Za-z-]*)", base)
    name = (m.group(1) if m else base).replace("-", " ").strip().lower()
    return name or "room"


def _geom_center(obj: JsonDict) -> XY | None:
    g = obj.get("geometry") or {}
    c = g.get("center")
    if isinstance(c, (list, tuple)) and len(c) >= 2:
        return (float(c[0]), float(c[1]))
    s, e = g.get("start"), g.get("end")
    if isinstance(s, (list, tuple)) and isinstance(e, (list, tuple)):
        return ((float(s[0]) + float(e[0])) / 2.0, (float(s[1]) + float(e[1])) / 2.0)
    return None


def _object_noun(obj: JsonDict) -> str | None:
    t = str(obj.get("type") or "").lower()
    if t in _DIRECT_TYPE_NOUN:
        return _DIRECT_TYPE_NOUN[t]
    fac = str((obj.get("metadata") or {}).get("factory") or "").lower()
    for key, noun in _FACTORY_NOUN.items():
        if key in fac:
            return noun
    return None


@dataclass
class InstructionContext:
    """Per-scene semantic lookup shared across all episodes of one scene."""
    rooms: list[tuple[str, tuple]] = field(default_factory=list)       # (name, footprint)
    objects: list[tuple[str, float, float]] = field(default_factory=list)  # (noun, x, y)
    mirrors: list[XY] = field(default_factory=list)
    glass: list[XY] = field(default_factory=list)
    goal_label: str = "the goal"
    hazard_label: str = "transparent partition"

    def node_room(self, x: float, y: float) -> str | None:
        """Smallest-area room footprint containing (x, y), or None."""
        best: tuple[float, str] | None = None
        for name, fp in self.rooms:
            if point_in_footprint(x, y, fp):
                bx0, by0, bx1, by1 = footprint_bbox(fp)
                area = abs((bx1 - bx0) * (by1 - by0))
                if best is None or area < best[0]:
                    best = (area, name)
        return best[1] if best else None

    def nearest_object(self, x: float, y: float, *, max_dist: float = _NEAR_OBJECT_M):
        best = None
        for noun, ox, oy in self.objects:
            d = math.hypot(ox - x, oy - y)
            if d <= max_dist and (best is None or d < best[1]):
                best = (noun, d, ox, oy)
        return best  # (noun, dist, x, y) | None


def build_instruction_context(
    graph: Any,
    annotation: Any | None,
    authoring_map: JsonDict | None,
    perturbation: JsonDict | None,
) -> InstructionContext:
    ctx = InstructionContext()
    am = authoring_map or {}

    # Rooms from infinigen .floor structure objects; fall back to traversable regions.
    for o in am.get("objects") or []:
        md = o.get("metadata") or {}
        bn = str(md.get("blender_name") or "")
        if str(md.get("kind")) == "structure" and bn.endswith(".floor"):
            fp = object_footprint(o.get("geometry") or {})
            if fp is not None:
                ctx.rooms.append((_clean_room_name(bn), fp))
    if not ctx.rooms:
        for r in am.get("regions") or []:
            if str(r.get("type")) != "traversable":
                continue
            fp = object_footprint(r.get("geometry") or {})
            if fp is not None:
                ctx.rooms.append((_clean_room_name(str(r.get("label") or r.get("id") or "room"), is_label=True), fp))

    # Notable objects.
    for o in am.get("objects") or []:
        if str((o.get("metadata") or {}).get("kind")) == "structure":
            continue
        noun = _object_noun(o)
        c = _geom_center(o)
        if noun and c is not None:
            ctx.objects.append((noun, c[0], c[1]))

    # Mirror / glass positions (authoring + perturbation sidecar).
    def _collect(objs):
        for o in objs or []:
            t = str(o.get("type") or "")
            c = _geom_center(o)
            if c is None:
                continue
            if t == "mirror_wall":
                ctx.mirrors.append(c)
            elif t in ("glass_wall", "glass_door", "transparent_partition"):
                ctx.glass.append(c)
    _collect(am.get("objects"))
    _collect((perturbation or {}).get("objects"))

    if annotation is not None:
        goals = getattr(annotation, "goal_regions", None) or []
        if goals:
            label = goals[0].label or goals[0].region_id
            # A bare "Goal"/"goal" reads awkwardly inside a sentence ("reach Goal").
            ctx.goal_label = "the goal" if str(label).strip().lower() in ("goal", "the goal") else label
        hazards = getattr(annotation, "hazard_regions", None) or []
        if hazards:
            ctx.hazard_label = hazards[0].hazard_type.replace("_", " ")
    return ctx


@dataclass
class EpisodeCore:
    """Per-episode inputs the generators read (no graph/annotation objects)."""
    episode_id: str
    scenario: str
    path_nodes: list[str]
    node_xy: dict[str, XY]
    expanded_steps: list[tuple[str, str, str, dict]]  # (node, heading, action, meta)
    goal_label: str


# --------------------------------------------------------------------------- #
# Generators — each returns 0+ Instruction dicts. Register in GENERATORS.      #
# --------------------------------------------------------------------------- #

def gen_goal_scenario(core: EpisodeCore, ctx: InstructionContext) -> list[Instruction]:
    """The original goal/hazard-scenario instruction (back-compat primary)."""
    g, h = core.goal_label, ctx.hazard_label
    text = {
        "hazard_aware": f"Go to {g} without crossing the {h}.",
        "stop_before_glass": f"Move toward {g} and stop before the {h}.",
        "detour": f"Go to {g} by taking the safe detour around the {h}.",
    }.get(core.scenario, f"Go to {g}.")
    return [{"type": "goal", "level": "goal", "text": text, "lang": "en",
             "source": "template", "grounding": {"goal": g, "scenario": core.scenario}}]


def gen_turn_by_turn(core: EpisodeCore, ctx: InstructionContext) -> list[Instruction]:
    """Geometric turn-by-turn from the expanded primitive action sequence."""
    phrases: list[str] = []
    turn_run = 0  # signed accumulated 30° steps (+left / -right)

    def flush_turn():
        nonlocal turn_run
        if turn_run:
            deg = abs(turn_run) * 30
            phrases.append(f"turn {'left' if turn_run > 0 else 'right'} {deg}°")
            turn_run = 0

    for _node, _h, action, _meta in core.expanded_steps[:_MAX_TURN_STEPS]:
        if action == "turn_left_30":
            turn_run += 1
        elif action == "turn_right_30":
            turn_run -= 1
        elif action == "move_forward":
            flush_turn()
            phrases.append("go forward")
        elif action == "stop":
            flush_turn()
            phrases.append("stop")
    flush_turn()
    if not phrases:
        return []
    # Collapse consecutive identical "go forward" into one.
    compact: list[str] = []
    for p in phrases:
        if p == "go forward" and compact and compact[-1] == "go forward":
            continue
        compact.append(p)
    text = ", ".join(compact)
    text = text[0].upper() + text[1:] + ("." if not text.endswith(".") else "")
    return [{"type": "turn_by_turn", "level": "geometric", "text": text, "lang": "en",
             "source": "template", "grounding": {"steps": len(core.expanded_steps)}}]


def gen_landmark_chain(core: EpisodeCore, ctx: InstructionContext) -> list[Instruction]:
    """Semantic room/object chain along the path."""
    if not ctx.rooms and not ctx.objects:
        return []
    legs: list[str] = []
    grounding_rooms: list[str] = []
    last_room: str | None = None
    object_cue: str | None = None
    for i, node in enumerate(core.path_nodes):
        xy = core.node_xy.get(node)
        if xy is None:
            continue
        room = ctx.node_room(xy[0], xy[1])
        if room and room != last_room:
            legs.append(f"go to the {room}" if not legs else f"then the {room}")
            grounding_rooms.append(room)
            last_room = room
        # One object cue around the middle of the path for flavour/grounding.
        if object_cue is None and 0 < i < len(core.path_nodes) - 1:
            near = ctx.nearest_object(xy[0], xy[1])
            if near:
                object_cue = near[0]
    if not legs and object_cue is None:
        return []
    parts = list(legs)
    if object_cue:
        parts.append(f"pass the {object_cue}")
    parts.append(f"and reach {core.goal_label}")
    text = ", ".join(parts)
    text = text[0].upper() + text[1:] + "."
    return [{"type": "landmark", "level": "semantic", "text": text, "lang": "en",
             "source": "template",
             "grounding": {"rooms": grounding_rooms, "object": object_cue, "goal": core.goal_label}}]


def gen_perception_aware(core: EpisodeCore, ctx: InstructionContext) -> list[Instruction]:
    """Mirror/glass-aware instruction — only when a hazard lies near the path."""
    if not ctx.mirrors and not ctx.glass:
        return []
    xs = [core.node_xy[n] for n in core.path_nodes if n in core.node_xy]
    if len(xs) < 2:
        return []

    def _side(i: int, hx: float, hy: float) -> str:
        a = xs[i]
        b = xs[i + 1] if i + 1 < len(xs) else xs[i - 1]
        tx, ty = b[0] - a[0], b[1] - a[1]
        cross = tx * (hy - a[1]) - ty * (hx - a[0])
        return "left" if cross > 0 else "right"

    def _first_hit(points):
        for i, (px, py) in enumerate(xs):
            for hx, hy in points:
                if math.hypot(hx - px, hy - py) <= _HAZARD_NEAR_M:
                    return _side(i, hx, hy)
        return None

    m_side = _first_hit(ctx.mirrors)
    g_side = _first_hit(ctx.glass)
    if m_side is None and g_side is None:
        return []
    clauses = []
    if m_side:
        clauses.append(f"you will pass a mirror on your {m_side} — ignore the reflection")
    if g_side:
        clauses.append(f"there is a glass wall on your {g_side} — do not try to walk through it")
    text = f"Head toward {core.goal_label}; " + "; ".join(clauses) + "."
    return [{"type": "perception", "level": "perception", "text": text, "lang": "en",
             "source": "template",
             "grounding": {"mirror_side": m_side, "glass_side": g_side, "goal": core.goal_label}}]


GENERATORS: list[Callable[[EpisodeCore, InstructionContext], list[Instruction]]] = [
    gen_goal_scenario,
    gen_turn_by_turn,
    gen_landmark_chain,
    gen_perception_aware,
]


def generate_instructions(
    core: EpisodeCore,
    ctx: InstructionContext,
    *,
    use_llm: bool = False,
    llm_variants: int = 2,
) -> list[Instruction]:
    """Run every template generator; optionally augment with codex paraphrases."""
    out: list[Instruction] = []
    seen: set[str] = set()
    for gen in GENERATORS:
        try:
            for ins in gen(core, ctx):
                key = ins["text"].strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    out.append(ins)
        except Exception:
            continue  # a broken generator must never abort episode generation
    if use_llm and out:
        try:
            from .instruction_paraphrase import paraphrase
            for ins in paraphrase(out, n_variants=llm_variants):
                key = ins["text"].strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    out.append(ins)
        except Exception:
            pass  # best-effort; template instructions already stand on their own
    return out
