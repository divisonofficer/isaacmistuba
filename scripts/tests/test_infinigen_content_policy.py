from infinigen_content_policy import effective_scene_seed


def test_effective_seed_is_stable_and_varies_by_room_and_variation() -> None:
    first = effective_scene_seed("20260814", "office", 0)
    assert first == effective_scene_seed("20260814", "office", 0)
    assert first != effective_scene_seed("20260814", "office", 1)
    assert first != effective_scene_seed("20260814", "bedroom", 0)
    assert 0 <= first < 100_000_000
