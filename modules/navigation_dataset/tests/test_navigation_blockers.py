from navigation_dataset.navigation_blockers import navigation_blocker_candidates


def test_navigation_blocker_candidates_are_large_removable_low_props_only():
    objects = [
        {
            "id": "floor", "type": "floor", "geometry": {"type": "point", "center": [0, 0], "size_m": [10, 0.02, 10]},
            "navigation": {"blocks_navigation": False},
        },
        {
            "id": "wall", "type": "wall", "geometry": {"type": "line", "start": [0, 0], "end": [10, 0], "thickness_m": 0.2},
            "navigation": {"blocks_navigation": True},
        },
        {
            "id": "ceiling_light", "type": "landmark", "is_emitter": True,
            "geometry": {"type": "point", "center": [1, 1], "size_m": [3, 0.2, 3]},
            "navigation": {"blocks_navigation": True},
        },
        {
            "id": "small-chair", "type": "chair", "geometry": {"type": "point", "center": [1, 1], "size_m": [0.7, 1, 0.7]},
            "navigation": {"blocks_navigation": True},
        },
        {
            "id": "large-bed", "type": "bed", "label": "Large bed",
            "geometry": {"type": "point", "center": [4, 4], "size_m": [2.5, 12.0, 3.0]},
            "navigation": {"blocks_navigation": True},
        },
        {
            "id": "explicitly-free", "type": "table", "geometry": {"type": "point", "center": [8, 8], "size_m": [3, 1, 3]},
            "navigation": {"blocks_navigation": False},
        },
    ]

    candidates = navigation_blocker_candidates(objects)

    assert [item["object_id"] for item in candidates] == ["large-bed"]
    assert candidates[0]["footprint_area_m2"] == 7.5
    assert "large_blocking_footprint" in candidates[0]["reasons"]
    assert "unusually_tall_geometry" in candidates[0]["reasons"]
