from navigation_dataset.apartment_quality import apply_blocker_and_orphan_policy, apply_lighting_profile


def _room_map():
    return {"regions": [{"id": "room", "type": "traversable", "geometry": {"bounds": [0, 0, 8, 6]}}],
            "objects": [], "environment": {"mode": "constant", "intensity": 1.0}}


def test_lighting_profile_adds_deduplicated_room_softbox_and_hdr():
    scene = _room_map()
    scene["objects"] = [{"id": "imported_lamp", "is_emitter": True, "geometry": {"type": "point", "center": [1, 1], "size_m": [.3, .1, .3]}}]
    result = apply_lighting_profile(scene, "softbox_hdr")
    assert result["softbox_count"] == 2
    assert scene["environment"]["mode"] == "envmap"
    assert scene["environment"]["envmap_ref"].endswith("env_rgb.exr")
    assert all(item["geometry"]["base_height_m"] == 2.55 for item in scene["objects"] if item["id"].startswith("light_softbox_"))
    assert sum(bool(item.get("is_emitter")) for item in scene["objects"]) == 2


def test_support_validation_removes_only_unsupported_tabletop_prop_after_blocker_removal():
    scene = _room_map()
    scene["objects"] = [
        {"id": "large_table", "type": "table", "geometry": {"type": "point", "center": [2, 2], "size_m": [3, 1, 3], "base_height_m": 0}, "navigation": {"blocks_navigation": True}},
        {"id": "DeskLamp_orphan", "type": "landmark", "geometry": {"type": "point", "center": [2, 2], "size_m": [.3, .4, .3], "base_height_m": 1.0}},
        {"id": "floor_chair", "type": "chair", "geometry": {"type": "point", "center": [5, 5], "size_m": [.7, 1, .7], "base_height_m": 0}},
    ]
    audit = apply_blocker_and_orphan_policy(scene, remove_blocker_ids=["large_table"])
    assert audit["removed_orphans"] == ["DeskLamp_orphan"]
    assert [obj["id"] for obj in scene["objects"]] == ["floor_chair"]


def test_supported_lamp_is_preserved():
    scene = _room_map()
    scene["objects"] = [
        {"id": "desk", "type": "desk", "geometry": {"type": "point", "center": [2, 2], "size_m": [2, 1, 2], "base_height_m": 0}},
        {"id": "DeskLamp_supported", "type": "landmark", "geometry": {"type": "point", "center": [2, 2], "size_m": [.3, .4, .3], "base_height_m": 1.0}},
    ]
    audit = apply_blocker_and_orphan_policy(scene)
    assert audit["removed_orphans"] == []
    assert len(scene["objects"]) == 2


def test_unsupported_book_is_removed_but_supported_book_is_preserved():
    scene = _room_map()
    scene["objects"] = [
        {"id": "BookFactory_orphan", "type": "landmark", "geometry": {"type": "point", "center": [1, 1], "size_m": [.2, .3, .2], "base_height_m": 1.2}},
        {"id": "shelf", "type": "shelf", "geometry": {"type": "point", "center": [4, 4], "size_m": [1, 1.2, 1], "base_height_m": 0}},
        {"id": "BookColumn_supported", "type": "landmark", "geometry": {"type": "point", "center": [4, 4], "size_m": [.3, .2, .3], "base_height_m": 1.2}},
    ]
    audit = apply_blocker_and_orphan_policy(scene)
    assert audit["removed_orphans"] == ["BookFactory_orphan"]
    assert {obj["id"] for obj in scene["objects"]} == {"shelf", "BookColumn_supported"}


def test_orphan_policy_rechecks_after_removing_a_false_support_chain():
    scene = _room_map()
    scene["objects"] = [
        {"id": "lamp_table", "type": "table", "geometry": {"type": "point", "center": [2, 2], "size_m": [.5, .4, .5], "base_height_m": 1.0}},
        {"id": "DeskLamp_chain", "type": "landmark", "geometry": {"type": "point", "center": [2, 2], "size_m": [.2, .2, .2], "base_height_m": 1.4}},
    ]
    audit = apply_blocker_and_orphan_policy(scene)
    assert audit["removed_orphans"] == ["DeskLamp_chain", "lamp_table"]
    assert audit["unsupported_after_policy"] == []
