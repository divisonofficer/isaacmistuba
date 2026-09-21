"""Repository-owned constraint additions for non-home Infinigen room tags."""
from __future__ import annotations

import math
import os
from collections import OrderedDict
from contextlib import contextmanager


#: Room-graph scales for the native (``apartment_natural_v1``) floor-plan solver.
#: Upstream caps a home at 15 interior rooms and 3 hallways, so no seed of the
#: native profile reaches a large multi-corridor residence -- observed counts sit
#: at 5-11.
#:
#: ``GraphMaker`` samples a candidate room graph and keeps it only when the
#: ``node`` constraint reports no violation.  Instrumenting that check showed
#: upstream already proposing 19-room candidates and discarding them against the
#: 15-room bound, so a scale mostly just moves the acceptance window; the room
#: relations that make a layout read as a home are left as upstream wrote them.
#: ``branch_factor`` nudges the branching means on top of that, and is kept small
#: on purpose -- at 1.75 candidates ran to 36 rooms, overshot the window, and the
#: sampler never accepted one.  Measured room counts per scale sit in
#: ``room_count_target``; the sampler is stochastic, so that is recorded in the
#: scene preset rather than enforced.
#:
#: Measured with the real gin overrides: upstream yields 5-13 interior rooms.
#: Which room types a ``branch_factor`` is allowed to spawn more of.  Widening
#: every count instead grew the house out of its leaves: 5 seeds averaged 5.6
#: bathrooms and 3.6 closets against 3.0 bedrooms and 1.2 hallways, which is
#: neither a plausible home nor the corridor topology a navigation episode needs.
#: Bathrooms, closets, balconies and utility rooms keep their upstream rates and
#: arrive as consequences of the bedrooms and corridors that now exist.
_SPINE_ROOM_TYPES = ("LivingRoom", "Hallway", "Bedroom")

ROOM_GRAPH_SCALES: dict[str, dict] = {
    "large_residence_v1": {
        "branch_factor": 1.2,
        "branch_room_types": _SPINE_ROOM_TYPES,
        "total_rooms": (16, 26),
        "hallways": (0, 5),
        "room_count_target": 20,
    },
}

#: The two upstream caps a scale rewrites, keyed by their current ``(low, high)``.
#: Matching on the value rather than tree position keeps the rewrite honest: an
#: upstream change to either bound fails loudly instead of silently capping the
#: house at 15 rooms again.
_TOTAL_ROOM_CAP = (4, 15)
_HALLWAY_CAP = (0, 3)


def _walk(expression):
    """Yield an expression node and everything below it."""
    stack = [expression]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(child for _, child in node.children())


def _in_range_nodes(expression):
    """Yield every ``in_range`` node in a constraint expression tree."""
    from infinigen.core.constraints import constraint_language as cl

    for node in _walk(expression):
        if isinstance(node, cl.in_range):
            yield node


def _counts_room_type(node, semantic) -> bool:
    """Does this branch count constrain how many rooms of ``semantic`` appear?"""
    return any(semantic in (getattr(sub, "tags", None) or ()) for sub in _walk(node))


def scale_room_graph_problem(problem, scale: str) -> dict:
    """Widen a home room-graph problem so the solver builds a larger residence.

    ``problem`` is the ``cl.Problem`` returned by ``home_room_constraints``; its
    expression nodes are mutable dataclasses, so the grammar is rewritten in
    place and every relation between room types is preserved exactly.

    Branching is only widened when a scale asks for it.  Even then a count with
    ``low == high`` is left alone: it states a structural fact -- a dining room
    has exactly one kitchen, a balcony exactly one exterior -- so scaling it
    produces two kitchens per dining room rather than a bigger house.
    """
    spec = ROOM_GRAPH_SCALES.get(scale)
    if spec is None:
        raise ValueError(f"unknown room graph scale {scale!r}; have {sorted(ROOM_GRAPH_SCALES)}")
    branch_factor = float(spec["branch_factor"])

    widened = 0
    if branch_factor != 1.0:
        from infinigen.core.tags import Semantics

        scope = [getattr(Semantics, name) for name in spec["branch_room_types"]]
        for node in _in_range_nodes(problem.constraints["node_gen"]):
            if node.low >= node.high:
                continue
            if not any(_counts_room_type(node, semantic) for semantic in scope):
                continue
            node.high = int(math.ceil(node.high * branch_factor))
            node.mean = node.mean * branch_factor
            widened += 1

    # A one-storey home may hold no staircase room -- ``node`` states exactly
    # that -- yet the grammar still spawns one off living rooms and hallways at
    # mean 0.5/0.4.  Every draw that takes the offer is thrown away, and a larger
    # house offers it more often, so on a wide acceptance window the sampler
    # spends nearly all its candidates on graphs it must reject.  Stop proposing
    # what this scene can never keep.
    suppressed = 0
    if getattr(problem.constants, "n_stories", 1) == 1:
        from infinigen.core.tags import Semantics

        for node in _in_range_nodes(problem.constraints["node_gen"]):
            if _counts_room_type(node, Semantics.StaircaseRoom):
                node.low, node.high, node.mean = 0, 0, 0.0
                suppressed += 1

    caps = {}
    for node in _in_range_nodes(problem.constraints["node"]):
        current = (node.low, node.high)
        if current == _TOTAL_ROOM_CAP:
            node.low, node.high = spec["total_rooms"]
            caps["total_rooms"] = tuple(spec["total_rooms"])
        elif current == _HALLWAY_CAP:
            node.low, node.high = spec["hallways"]
            caps["hallways"] = tuple(spec["hallways"])
    missing = {"total_rooms", "hallways"} - set(caps)
    if missing:
        raise RuntimeError(
            f"room graph scale {scale!r} could not find the upstream {sorted(missing)} cap; "
            "infinigen_examples.constraints.home.home_room_constraints has changed"
        )
    record = {"scale": scale, "branch_factor": branch_factor, "widened_branch_counts": widened,
              "suppressed_staircase_branches": suppressed,
              "room_count_target": spec["room_count_target"], **caps}
    print(f"[robomituba] room graph scale applied: {record}", flush=True)
    return record


def office_asset_usage() -> dict:
    """Return the complete, deliberately small asset registry for office v2.

    V2 does not begin with the home registry and filter its output: domestic
    factories are never candidates in the first place.  The Blender audit is
    retained as a defence-in-depth check for indirectly created assets.
    """
    from infinigen.assets.objects import appliances, bathroom, lamp, seating, shelves, tables
    from infinigen.core.tags import Semantics

    primary = {
        shelves.SimpleDeskFactory, seating.OfficeChairFactory, seating.ChairFactory,
        tables.TableDiningFactory, bathroom.ToiletFactory, bathroom.BathroomSinkFactory,
        shelves.LargeShelfFactory, appliances.BeverageFridgeFactory,
    }
    secondary = {appliances.MonitorFactory, lamp.CeilingLightFactory}
    return {
        Semantics.Furniture: primary,
        Semantics.Storage: {shelves.LargeShelfFactory},
        Semantics.Table: {shelves.SimpleDeskFactory, tables.TableDiningFactory},
        Semantics.Desk: {shelves.SimpleDeskFactory},
        Semantics.Seating: {seating.OfficeChairFactory, seating.ChairFactory},
        Semantics.Chair: {seating.OfficeChairFactory, seating.ChairFactory},
        Semantics.Sink: {bathroom.BathroomSinkFactory},
        Semantics.KitchenAppliance: {appliances.BeverageFridgeFactory},
        Semantics.Lighting: {lamp.CeilingLightFactory},
        Semantics.CeilingLight: {lamp.CeilingLightFactory},
        Semantics.Object: primary | secondary,
        # ``sample_rand_placeholder()`` unconditionally queries all of these
        # usage categories. Empty categories must therefore be declared too;
        # otherwise the first solver addition aborts with an assertion instead
        # of treating the factory as a normal bounding-box placeholder.
        Semantics.SingleGenerator: {
            lamp.CeilingLightFactory, seating.ChairFactory, seating.OfficeChairFactory,
        },
        Semantics.RealPlaceholder: {
            appliances.MonitorFactory, bathroom.BathroomSinkFactory,
            bathroom.ToiletFactory, seating.ChairFactory,
        },
        Semantics.AssetAsPlaceholder: set(),
        Semantics.PlaceholderBBox: set(),
        Semantics.AssetPlaceholderForChildren: {shelves.LargeShelfFactory},
        Semantics.NoRotation: {lamp.CeilingLightFactory},
        Semantics.NoCollision: set(),
        Semantics.NoChildren: {lamp.CeilingLightFactory},
    }


def validate_office_asset_usage(usage: dict) -> None:
    """Fail before solver startup if a mandatory placement metadata tag is absent."""
    from infinigen.core.tags import Semantics

    mandatory = {
        Semantics.SingleGenerator,
        Semantics.RealPlaceholder,
        Semantics.AssetAsPlaceholder,
        Semantics.PlaceholderBBox,
        Semantics.AssetPlaceholderForChildren,
        Semantics.NoRotation,
        Semantics.NoCollision,
        Semantics.NoChildren,
    }
    missing = mandatory - set(usage)
    if missing:
        raise RuntimeError("office v2 usage registry missing solver metadata: " + ", ".join(sorted(tag.value for tag in missing)))


def office_furniture_constraints(richness: int):
    """Build an independent ``modern_glass_office_v2`` constraint graph.

    It deliberately does *not* call ``home_furniture_constraints``: home
    fullness terms and its domestic registry caused the old office generator
    to put household assets into a small region of the floorplate.
    """
    from infinigen.assets.objects import appliances, bathroom, lamp, seating, shelves, tables
    from infinigen.core.constraints import constraint_language as cl, usage_lookup
    from infinigen.core.tags import Semantics
    from infinigen_examples.constraints import util as cu

    usage = office_asset_usage()
    validate_office_asset_usage(usage)
    usage_lookup.initialize_from_dict(usage)
    rooms = cl.scene()[{Semantics.Room, -Semantics.Object}]
    objects = cl.scene()[{Semantics.Object, -Semantics.Room}]
    furniture = objects[Semantics.Furniture].related_to(rooms, cu.on_floor)
    wallfurn = furniture.related_to(rooms, cu.against_wall)
    desks = wallfurn[shelves.SimpleDeskFactory]
    meeting_chairs = furniture[seating.ChairFactory]
    # TableDiningFactory is sampled in the same floor placement stage as
    # chairs, and a valid break/meeting table may touch a wall. Restricting
    # the quota to the ``-against_wall`` subset made the solver see zero
    # tables even while a table candidate was present, leaving a permanent
    # break-room violation. Keep the semantic room relation authoritative and
    # let the post-generation audit handle clearance/distribution.
    meeting_tables = furniture[tables.TableDiningFactory]
    wall_objects = objects.related_to(rooms, cu.on_floor).related_to(rooms, cu.against_wall)
    toilets = wall_objects[bathroom.ToiletFactory]
    sinks = wall_objects[bathroom.BathroomSinkFactory]
    shelves_ = wallfurn[shelves.LargeShelfFactory]
    fridges = wallfurn[appliances.BeverageFridgeFactory]
    # Do not make chair-to-desk orientation a hard Infinigen solver relation.
    # Infinigen must initialise the chair while simultaneously satisfying room,
    # desk-facing and collision relations; wide-office scenes repeatedly get
    # stuck in that search state.  We solve room-local chair quotas here, then
    # place a deterministic chair in front of each desk in Blender after the
    # geometry phase (and verify its collision/door clearance there).
    office_chairs = furniture[seating.OfficeChairFactory]
    # Monitors are audited by room after Blender evaluates the generated
    # geometry.  Requiring every individual desk to carry an ``ontop`` and
    # ``back_coplanar_back`` relation in the solver is too brittle: the final
    # ``obj_ontop_obj`` pass can leave a handful of desks without a direct
    # relation even though the room has the required monitor population.
    # Keep the original desk domain (so greedy-stage coverage remains valid)
    # but make the lower bound advisory; the Blender audit remains the
    # authoritative aggregate quota.
    desk_monitors = objects[appliances.MonitorFactory].related_to(desks, cu.ontop).related_to(desks, cu.back_coplanar_back)
    ceiling_lights = objects[lamp.CeilingLightFactory]

    work_bays = rooms[Semantics.OpenOffice]
    focus_rooms = rooms[Semantics.Office]
    meeting_rooms = rooms[Semantics.MeetingRoom]
    break_rooms = rooms[Semantics.BreakRoom]
    restrooms = rooms[Semantics.Restroom]
    storage_rooms = rooms[Semantics.Warehouse]
    reception_support = rooms[Semantics.FactoryOffice]
    constraints = OrderedDict()
    # Keep the lower quota (the dataset contract) but do not turn the
    # sampler's natural density into a hard failure. The old 6--10 ceiling
    # rejected a valid wide bay as soon as it received an extra workstation;
    # occupancy/distribution is checked by the later Blender audit instead.
    constraints["robomituba_v2_work_bays"] = work_bays.all(
        lambda r: desks.related_to(r).count().in_range(6, 64)
        * office_chairs.related_to(r).count().in_range(6, 64)
    )
    constraints["robomituba_v2_focus_rooms"] = focus_rooms.all(
        lambda r: desks.related_to(r).count().in_range(1, 32)
        * office_chairs.related_to(r).count().in_range(1, 32)
    )
    # Meeting-room furniture is validated from the evaluated Blender geometry
    # by ``office_population_audit``.  Keeping this as a solver hard relation
    # is unsafe: the upstream on-floor/freestanding stages may place a valid
    # table or chair without preserving the authored room relation, leaving a
    # permanent ``meeting-room: 1`` violation while the solver repeatedly
    # creates/deletes ChairFactory objects.  This is the same boundary used
    # for break-room furniture below; the post-generation audit still requires
    # one table and at least six chairs in every meeting room.
    # Break-room furniture is deliberately *not* a solver hard constraint.
    # Infinigen's on-floor/freestanding stages do not always preserve the
    # authored room relation for TableDining/ChairFactory, so a seemingly
    # generous count here can still leave a permanent ``break-room: 1``
    # violation at the final solve pass.  The workstation/population audit
    # evaluates the actual Blender geometry and reports missing/invalid break
    # furniture after generation; failing the whole candidate in the generic
    # solver provides no useful signal and makes deterministic seeds loop.
    constraints["robomituba_v2_restrooms"] = restrooms.all(
        lambda r: toilets.related_to(r).count().in_range(1, 64) * sinks.related_to(r).count().in_range(1, 64)
    )
    constraints["robomituba_v2_storage"] = storage_rooms.all(lambda r: shelves_.related_to(r).count().in_range(1, 64))
    constraints["robomituba_v2_reception_support"] = reception_support.all(
        lambda r: desks.related_to(r).count().in_range(1, 64)
        * office_chairs.related_to(r).count().in_range(1, 64)
    )
    # Monitor placement is intentionally advisory at solver time.  A positive
    # lower bound here repeatedly left exactly a few unresolved monitor
    # bindings in the final small-object pass and aborted otherwise valid
    # seeds.  The population audit still requires >=6 monitors in every work
    # bay and >=1 in focus/reception rooms; geometric desk pairing is not
    # asserted by the solver and remains a post-process/audit concern.
    constraints["robomituba_v2_workstation_monitors"] = desks.all(
        lambda desk: desk_monitors.related_to(desk, cu.ontop).count().in_range(0, 8)
    )
    constraints["robomituba_v2_lighting"] = rooms.all(lambda room: ceiling_lights.related_to(room, cu.hanging).count().in_range(1, 16))
    return cl.Problem(constraints=constraints, score_terms=OrderedDict())


@contextmanager
def room_content_program(room_type: str, anchor_richness: str = "balanced",
                         program: str = "", placement_profile: str = "legacy_clutter_v1",
                         room_scale: str = ""):
    """Temporarily tune the upstream home programme for one generation run.

    Infinigen is commonly invoked repeatedly from a long-lived Blender Python
    process.  Leaving module-level monkey patches installed made a later,
    unrelated room inherit the previous job's fullness setting.  Keep native
    solver constraints authoritative and restore both patched callables even
    when generation fails.
    """
    # The room programmes below -- robomituba_office_program and its siblings --
    # have never run. custom_program is true for exactly the room types they
    # handle, and line "if custom_program: return problem" sits above them, so
    # every branch from `elif room_type in {"office", ...}` down is unreachable.
    # A work room therefore gets Infinigen's home constraints, which do not know
    # what an office contains: tripling an office's floor area moved it from 17
    # objects to 20, because nothing was asking for desks.
    #
    # The guard was added because a second count constraint can span Infinigen's
    # greedy placement stages and trip its non-overlap assertion before solve.
    # That was real -- two such errors appear the moment it is lifted -- but the
    # cause was a factory left unscoped to one placement stage, not the count
    # constraints themselves, and both are fixed above. The programmes run by
    # default now. Set ROBOMITUBA_FORCE_ROOM_PROGRAM=0 to restore the skip
    # without editing code: only office has been checked end to end at the time
    # this default flipped, and a room type whose programme still spans a stage
    # would fail at solve rather than degrade quietly.
    force_program = os.environ.get("ROBOMITUBA_FORCE_ROOM_PROGRAM", "1") != "0"
    custom_program = (
        not force_program
        and (room_type in {"office", "factory-office", "open-office", "meeting-room",
                           "restroom", "warehouse", "garage", "break-room"}
             or program in {"modern_office", "modern_glass_office_v2"})
    )
    from infinigen.assets.objects import appliances, bathroom, elements, seating, shelves, tables
    from infinigen.core.constraints import constraint_language as cl
    from infinigen.core.tags import Semantics
    from infinigen_examples.constraints import home as home_constraints
    from infinigen_examples.constraints import util as cu

    original = home_constraints.home_furniture_constraints
    richness = {"minimal": 1, "balanced": 2, "rich": 3, "storage": 4}.get(anchor_richness, 2)
    original_params = home_constraints.sample_home_constraint_params
    original_rooms = home_constraints.home_room_constraints
    room_scale_record: dict = {}
    if room_scale and room_scale not in ROOM_GRAPH_SCALES:
        # Fail before Blender spends minutes solving with an unscaled grammar.
        raise ValueError(f"unknown room graph scale {room_scale!r}; have {sorted(ROOM_GRAPH_SCALES)}")

    def scaled_rooms(*args, **kwargs):
        problem = original_rooms(*args, **kwargs)
        room_scale_record.update(scale_room_graph_problem(problem, room_scale))
        return problem

    def content_params():
        params = original_params()
        params["furniture_fullness_pct"] = {"minimal": 0.38, "balanced": 0.58, "rich": 0.74, "storage": 0.84}.get(anchor_richness, 0.58)
        return params

    def wrapped(*args, **kwargs):
        # Infinigen's greedy placement stages intentionally partition the
        # upstream semantic programme.  Adding a second count constraint for a
        # factory (Bed/Toilet/etc.) spans multiple stages and causes its hard
        if program == "modern_glass_office_v2":
            return office_furniture_constraints(richness)
        problem = original(*args, **kwargs)
        # Infinigen's greedy placement stages intentionally partition the
        # upstream semantic programme.  Adding a second count constraint for a
        # factory (Bed/Toilet/etc.) spans multiple stages and causes its hard
        # non-overlap assertion before generation.  The legacy paths below
        # therefore retain the upstream home graph unchanged.
        if custom_program:
            return problem
        rooms = cl.scene()[{Semantics.Room, -Semantics.Object}]
        objects = cl.scene()[{Semantics.Object, -Semantics.Room}]
        furniture = objects[Semantics.Furniture].related_to(rooms, cu.on_floor)
        # Not every floor-standing thing carries Semantics.Furniture, and
        # asking for it where the generator does not declare it is fatal:
        #   requested BathroomSinkFactory with {..., Semantics.Furniture, ...}
        #   but used_as[] tags specify {..., Semantics.Sink, ...} so predicates
        #   remainder={Semantics.Furniture} are unsatisfied
        # RackFactory declares neither Furniture nor Object. Scope those by
        # placement alone, which is what office_furniture_constraints does for
        # the same factories.
        floor_objects = objects.related_to(rooms, cu.on_floor)
        wall_objects = floor_objects.related_to(rooms, cu.against_wall)
        if program == "modern_office":
            # The base Infinigen programme already dispatches by room semantic
            # (OpenOffice, MeetingRoom, Office, BreakRoom, Restroom, Warehouse).
            # Adding second object-count constraints here makes its greedy
            # placement stages overlap (for example MonitorFactory can be placed
            # both on-floor and on-wall), which Infinigen rejects before solve.
            # Keep the semantic layout and richness-adjusted global fullness,
            # but let the upstream programme own its placement domains.
            pass
        elif room_type in {"office", "factory-office", "open-office"}:
            # Every factory in a count constraint must sit in exactly one greedy
            # placement stage. `furniture` is already scoped to on_floor; a bare
            # `objects[...]` is not, and Infinigen refuses before solve:
            #   Object class Bound(domain=...MonitorFactory..., low=1, high=13)
            #   was covered in more than one greedy stage! Got coverage=
            #   ['on_floor_and_wall','on_floor_freestanding','on_wall','on_ceiling']
            # office_furniture_constraints above already has the right shape for
            # a monitor -- ontop of a desk -- so use it rather than inventing one.
            desks = furniture[shelves.SimpleDeskFactory]
            chairs = furniture[seating.OfficeChairFactory]
            monitors = objects[appliances.MonitorFactory].related_to(desks, cu.ontop)
            beds = furniture[seating.BedFactory]
            problem.constraints["robomituba_office_program"] = rooms.all(
                lambda room: desks.related_to(room).count().in_range(1, richness + 2)
                * chairs.related_to(room).count().in_range(1, richness * 3 + 1)
                * beds.related_to(room).count().equals(0))
            # A monitor sits on a desk, not in a room, so counting it per room
            # leaves the relation unnamed and the solver refuses:
            #   had underspecified first=(AnyRelation(), Domain({Semantics.Room...
            # Count it per desk with the relation named, which is the shape
            # office_furniture_constraints already uses for the same object.
            problem.constraints["robomituba_office_monitors"] = desks.all(
                lambda desk: monitors.related_to(desk, cu.ontop).count().in_range(0, 2))
        elif room_type == "meeting-room":
            meeting_tables = furniture[tables.TableDiningFactory]
            chairs = furniture[seating.ChairFactory]
            beds = furniture[seating.BedFactory]
            toilets = wall_objects[bathroom.ToiletFactory]
            problem.constraints["robomituba_meeting_program"] = rooms.all(
                lambda room: meeting_tables.related_to(room).count().in_range(1, 2)
                * chairs.related_to(room).count().in_range(4, 4 + richness * 3)
                * beds.related_to(room).count().equals(0) * toilets.related_to(room).count().equals(0))
        elif room_type == "restroom":
            toilets = wall_objects[bathroom.ToiletFactory]
            sinks = wall_objects[bathroom.BathroomSinkFactory]
            beds = furniture[seating.BedFactory]
            problem.constraints["robomituba_restroom_program"] = rooms.all(
                lambda room: toilets.related_to(room).count().in_range(1, richness + 2)
                * sinks.related_to(room).count().in_range(1, richness + 2)
                * beds.related_to(room).count().equals(0))
        elif room_type in {"warehouse", "garage"}:
            shelves_ = wall_objects[shelves.LargeShelfFactory]
            beds = furniture[seating.BedFactory]
            # RackFactory is left out on purpose. Its used_as[] tags are
            # {Semantics.RealPlaceholder, FromGenerator(RackFactory)} -- neither
            # Semantics.Object nor Semantics.Furniture -- so every domain this
            # module can build excludes it, and requesting it is fatal rather
            # than merely unsatisfied. Shelving carries the constraint; racks
            # still appear if the upstream programme places them, they just
            # cannot be counted here until the generator declares a tag.
            problem.constraints["robomituba_storage_program"] = rooms.all(
                lambda room: shelves_.related_to(room).count().in_range(1, richness * 3 + 1)
                * beds.related_to(room).count().equals(0))
        elif room_type == "break-room":
            tables_ = furniture[tables.TableDiningFactory]
            chairs = furniture[seating.ChairFactory]
            beds = furniture[seating.BedFactory]
            problem.constraints["robomituba_break_program"] = rooms.all(
                lambda room: tables_.related_to(room).count().in_range(1, richness + 1)
                * chairs.related_to(room).count().in_range(2, richness * 3 + 2)
                * beds.related_to(room).count().equals(0))
        return problem

    # Paper-style pilots keep the upstream residential fullness distribution
    # (currently uniform 0.6--0.9), so ``upstream_residential_v1`` is the one
    # profile that must not see the richness mapping.  Every clutter profile
    # applies it: ``anchor_richness`` selects how much medium/large furniture a
    # room carries, which is orthogonal to whether clutter placement is
    # collision-checked.  Leaving it legacy-only silently dropped the requested
    # richness whenever collision-aware placement was chosen.
    if placement_profile in {"legacy_clutter_v1", "collision_aware_clutter_v1"}:
        home_constraints.sample_home_constraint_params = content_params
    home_constraints.home_furniture_constraints = wrapped
    # The room graph is solved before any furniture, and only the native
    # floor-plan solver consults it; a predefined floor-plan JSON supplies its
    # own rooms and is unaffected by the scale.
    if room_scale:
        home_constraints.home_room_constraints = scaled_rooms
    try:
        yield {"custom_program": custom_program, "placement_profile": placement_profile,
               "room_scale": room_scale or None, "room_scale_detail": room_scale_record}
    finally:
        home_constraints.sample_home_constraint_params = original_params
        home_constraints.home_furniture_constraints = original
        home_constraints.home_room_constraints = original_rooms
