from mitsuba_converter.ir_scene_content import audit_scene_content


def _obj(factory: str) -> dict:
    return {"type": "landmark", "metadata": {"factory": factory}}


def test_office_program_accepts_anchors_and_rejects_bedroom_content() -> None:
    passed = audit_scene_content({"objects": [_obj("SimpleDeskFactory"), _obj("OfficeChairFactory"),
                                                       _obj("MonitorFactory"), _obj("ShelfFactory")]}, room_type="office")
    assert passed["status"] == "passed"
    failed = audit_scene_content({"objects": [_obj("BedFactory") for _ in range(5)]}, room_type="office")
    assert failed["status"] == "failed"
    assert "forbidden_room_content" in failed["failures"]


def test_isolated_off_program_prop_is_a_warning() -> None:
    result = audit_scene_content(
        {"objects": [_obj("ClosetFactory") for _ in range(50)] + [_obj("BathtubFactory")]},
        room_type="closet",
    )
    assert result["status"] == "passed"
    assert result["forbidden_content_policy"]["status"] == "minor_warning"
    assert "minor_forbidden_room_content" in result["warnings"]
