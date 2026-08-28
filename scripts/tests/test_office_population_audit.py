from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_population_audit import audit_population  # noqa: E402


ROOMS = [
    "open-office_0/0", "open-office_0/1", "open-office_0/2",
    "meeting-room_0/0", "meeting-room_0/1", "meeting-room_0/2",
    "office_0/0", "office_0/1", "office_0/2", "office_0/3",
    "factory-office_0/0",
    "break-room_0/0", "restroom_0/0", "restroom_0/1", "warehouse_0/0",
]


def _manifest():
    segments = [{"segment_id": f"office_glass_v2_{index:02d}",
                 "door_opening_m": [[float(index), 0.0], [float(index), 1.0]]}
                for index in range(1, 11)]
    return {"profile": "modern_glass_office_v2", "room_ids": ROOMS,
            "work_bay_rooms": ROOMS[:3],
            "reception_support_rooms": ["factory-office_0/0"],
            "structural_glass": {"requested_partition_count": 10, "requested_pane_count": 20,
                                  "segments": segments},
            "installed_partition_ids": [segment["segment_id"] for segment in segments],
            "installed_pane_count": 20}


def _record(kind: str, room: str, index: int, cell=(0, 0)):
    factory = {
        "desk": "SimpleDeskFactory", "office_chair": "OfficeChairFactory", "monitor": "MonitorFactory",
        "chair": "ChairFactory", "meeting_table": "TableDiningFactory", "toilet": "ToiletFactory",
        "sink": "BathroomSinkFactory", "shelf": "LargeShelfFactory", "rack": "RackFactory",
    }.get(kind, "BedFactory")
    return {"asset_key": f"{factory}_{room}_{index}", "factory": factory, "room": room,
            "cell": list(cell)}


def _valid_records():
    result = []
    for bay in ROOMS[:3]:
        for index in range(6):
            cell = (index % 4, index // 4)
            result += [_record("desk", bay, index, cell), _record("office_chair", bay, index, cell),
                       _record("monitor", bay, index, cell)]
    for room in [x for x in ROOMS if x.startswith("office_")]:
        result += [_record("desk", room, 0), _record("office_chair", room, 0), _record("monitor", room, 0)]
    result += [_record("desk", "factory-office_0/0", 0), _record("office_chair", "factory-office_0/0", 0), _record("monitor", "factory-office_0/0", 0)]
    for room in [x for x in ROOMS if x.startswith("meeting-room_")]:
        result += [_record("meeting_table", room, 0)] + [_record("chair", room, i) for i in range(6)]
    result += [_record("meeting_table", "break-room_0/0", 0)] + [_record("chair", "break-room_0/0", i) for i in range(2)]
    for room in ["restroom_0/0", "restroom_0/1"]:
        result += [_record("toilet", room, 0), _record("sink", room, 0)]
    result += [_record("shelf", "warehouse_0/0", 0)]
    return result


def test_population_audit_accepts_complete_office():
    result = audit_population(_valid_records(), _manifest())
    assert result["status"] == "passed", result["errors"]


def test_population_audit_rejects_domestic_and_concentrated_work_bay():
    records = _valid_records()
    records.append({"asset_key": "BedFactory_1", "factory": "BedFactory", "room": "office_0/0", "cell": [0, 0]})
    for record in records:
        if record["room"] == "open-office_0/0" and record["factory"] in {"SimpleDeskFactory", "OfficeChairFactory"}:
            record["cell"] = [0, 0]
    result = audit_population(records, _manifest())
    assert result["status"] == "failed"
    assert any("domestic" in error for error in result["errors"])
    assert any("concentration" in error for error in result["errors"])


def test_population_audit_rejects_missing_room_quota_and_unassigned_asset():
    records = [record for record in _valid_records() if record["room"] != "restroom_0/1"]
    records.append(_record("desk", "not_a_room", 0))
    result = audit_population(records, _manifest())
    assert result["status"] == "failed"
    assert any("restroom_0/1" in error for error in result["errors"])
    assert result["unassigned_asset_keys"] == ["SimpleDeskFactory_not_a_room_0"]


def test_population_audit_rejects_failed_or_mismatched_workstation_postprocess():
    manifest = _manifest()
    manifest["workstation_layout"] = {
        "status": "failed", "layout_digest": "layout", "expected_rooms": ["open-office_0/0"],
    }
    result = audit_population(_valid_records(), manifest)
    assert result["status"] == "failed"
    assert any("workstation" in error for error in result["errors"])
