from mitsuba_converter.ir_dataset_readiness import build_readiness_label


def test_below_target_when_total_visible_proxy_is_below_ten() -> None:
    label = build_readiness_label(
        dataset_name="sparse",
        dataset_fingerprint="f" * 64,
        scene_statistics={
            "density_class": "sparse",
            "selected_pose_count": 400,
            "selected_visible_object_count": {"median": 2, "p90": 4},
        },
    )
    assert label["status"] == "below_target"
    assert "selected_visible_object_median_below_10" in label["findings"]
    assert label["criteria"]["specular_eligible_objects_per_view_min"] == 10


def test_proxy_pass_never_claims_specular_readiness() -> None:
    label = build_readiness_label(
        dataset_name="unknown-specular",
        dataset_fingerprint="e" * 64,
        scene_statistics={"selected_visible_object_count": {"median": 12, "p90": 16}},
    )
    assert label["status"] == "unverified"
    assert "specular_raster_evidence_missing" in label["findings"]


def test_missing_statistics_is_unverified() -> None:
    label = build_readiness_label(dataset_name="legacy", dataset_fingerprint="d" * 64,
                                  scene_statistics=None)
    assert label["status"] == "unverified"
    assert label["evidence"]["selected_visible_object_count"]["median"] is None
