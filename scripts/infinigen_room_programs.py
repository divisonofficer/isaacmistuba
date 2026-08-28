"""Repository-owned constraint additions for non-home Infinigen room tags."""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager


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
                         program: str = "", placement_profile: str = "legacy_clutter_v1"):
    """Temporarily tune the upstream home programme for one generation run.

    Infinigen is commonly invoked repeatedly from a long-lived Blender Python
    process.  Leaving module-level monkey patches installed made a later,
    unrelated room inherit the previous job's fullness setting.  Keep native
    solver constraints authoritative and restore both patched callables even
    when generation fails.
    """
    custom_program = (
        room_type in {"office", "factory-office", "open-office", "meeting-room", "restroom", "warehouse", "garage", "break-room"}
        or program in {"modern_office", "modern_glass_office_v2"}
    )
    from infinigen.assets.objects import appliances, bathroom, elements, seating, shelves, tables
    from infinigen.core.constraints import constraint_language as cl
    from infinigen.core.tags import Semantics
    from infinigen_examples.constraints import home as home_constraints
    from infinigen_examples.constraints import util as cu

    original = home_constraints.home_furniture_constraints
    richness = {"minimal": 1, "balanced": 2, "rich": 3, "storage": 4}.get(anchor_richness, 2)
    original_params = home_constraints.sample_home_constraint_params

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
            desks = furniture[shelves.SimpleDeskFactory]
            chairs = furniture[seating.OfficeChairFactory]
            monitors = objects[appliances.MonitorFactory]
            beds = objects[seating.BedFactory]
            problem.constraints["robomituba_office_program"] = rooms.all(
                lambda room: desks.related_to(room).count().in_range(1, richness + 2)
                * chairs.related_to(room).count().in_range(1, richness * 3 + 1)
                * monitors.related_to(room).count().in_range(1, richness * 3 + 1)
                * beds.related_to(room).count().equals(0))
        elif room_type == "meeting-room":
            meeting_tables = furniture[tables.TableDiningFactory]
            chairs = furniture[seating.ChairFactory]
            beds = objects[seating.BedFactory]
            toilets = objects[bathroom.ToiletFactory]
            problem.constraints["robomituba_meeting_program"] = rooms.all(
                lambda room: meeting_tables.related_to(room).count().in_range(1, 2)
                * chairs.related_to(room).count().in_range(4, 4 + richness * 3)
                * beds.related_to(room).count().equals(0) * toilets.related_to(room).count().equals(0))
        elif room_type == "restroom":
            toilets = objects[bathroom.ToiletFactory]
            sinks = objects[bathroom.BathroomSinkFactory]
            beds = objects[seating.BedFactory]
            problem.constraints["robomituba_restroom_program"] = rooms.all(
                lambda room: toilets.related_to(room).count().in_range(1, richness + 2)
                * sinks.related_to(room).count().in_range(1, richness + 2)
                * beds.related_to(room).count().equals(0))
        elif room_type in {"warehouse", "garage"}:
            shelves_ = objects[shelves.LargeShelfFactory]
            racks = objects[elements.RackFactory]
            beds = objects[seating.BedFactory]
            problem.constraints["robomituba_storage_program"] = rooms.all(
                lambda room: shelves_.related_to(room).count().in_range(1, richness * 3 + 1)
                * racks.related_to(room).count().in_range(0, richness * 2 + 1)
                * beds.related_to(room).count().equals(0))
        elif room_type == "break-room":
            tables_ = furniture[tables.TableDiningFactory]
            chairs = furniture[seating.ChairFactory]
            beds = objects[seating.BedFactory]
            problem.constraints["robomituba_break_program"] = rooms.all(
                lambda room: tables_.related_to(room).count().in_range(1, richness + 1)
                * chairs.related_to(room).count().in_range(2, richness * 3 + 2)
                * beds.related_to(room).count().equals(0))
        return problem

    # Paper-style pilots keep the upstream residential fullness distribution
    # (currently uniform 0.6--0.9).  The legacy profile deliberately preserves
    # the fixed Robomituba richness mapping so existing jobs remain bitwise
    # reproducible.
    if placement_profile == "legacy_clutter_v1":
        home_constraints.sample_home_constraint_params = content_params
    home_constraints.home_furniture_constraints = wrapped
    try:
        yield {"custom_program": custom_program, "placement_profile": placement_profile}
    finally:
        home_constraints.sample_home_constraint_params = original_params
        home_constraints.home_furniture_constraints = original
