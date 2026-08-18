"""Repository-owned constraint additions for non-home Infinigen room tags."""
from __future__ import annotations


def install_room_content_program(room_type: str, anchor_richness: str = "balanced",
                                 program: str = "") -> bool:
    custom_program = (
        room_type in {"office", "factory-office", "open-office", "meeting-room", "restroom", "warehouse", "garage", "break-room"}
        or program == "modern_office"
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

    home_constraints.sample_home_constraint_params = content_params

    def wrapped(*args, **kwargs):
        problem = original(*args, **kwargs)
        # Infinigen's greedy placement stages intentionally partition the
        # upstream semantic programme.  Adding a second count constraint for a
        # factory (Bed/Toilet/etc.) spans multiple stages and causes its hard
        # non-overlap assertion before generation.  Room semantics already
        # select the appropriate native programme, so retain only the global
        # fullness adjustment for every repository-managed room type.
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

    home_constraints.home_furniture_constraints = wrapped
    return custom_program
