from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "infinigen"))

from small_highpoly_filter import is_small_highpoly_record


def test_structural_mesh_is_always_protected():
    drop, reason = is_small_highpoly_record({
        "kind": "structure", "semantic_type": "wall", "dimensions": [0.1, 0.1, 0.1],
        "triangles": 999_999,
    })
    assert not drop and reason == "protected_kind"


def test_bounded_trinket_is_kept_for_pbr_supervision():
    drop, reason = is_small_highpoly_record({
        "kind": "furniture", "semantic_type": "landmark", "subtype": "prop",
        "factory": "NatureShelfTrinketsFactory", "dimensions": [0.2, 0.2, 0.2],
        "triangles": 250_000,
    })
    assert not drop and reason == "recoverable_pbr_detail"


def test_unknown_or_large_object_is_kept():
    assert not is_small_highpoly_record({
        "kind": "furniture", "semantic_type": "sink", "dimensions": [0.1, 0.1, 0.1],
        "triangles": 900_000,
    })[0]
    assert not is_small_highpoly_record({
        "kind": "furniture", "semantic_type": "landmark", "dimensions": [0.8, 0.8, 0.8],
        "triangles": 900_000,
    })[0]


def test_clustered_detail_gets_bounded_relaxed_extent():
    drop, reason = is_small_highpoly_record({
        "kind": "furniture", "semantic_type": "landmark",
        "factory": "FruitFactoryCompositional", "dimensions": [0.7, 0.6, 0.7],
        "triangles": 800_000,
    })
    assert drop and reason == "pathological_factory_filtered"


def test_book_column_decoration_is_not_treated_as_architectural_column():
    drop, reason = is_small_highpoly_record({
        "kind": "furniture", "semantic_type": "bookcolumn",
        "factory": "BookColumnFactory", "dimensions": [0.18, 0.18, 0.22],
        "triangles": 350_000,
    })
    assert not drop and reason == "recoverable_pbr_detail"


def test_book_column_factory_drops_even_when_parent_bbox_is_sparse():
    drop, reason = is_small_highpoly_record({
        "kind": "furniture", "semantic_type": "landmark",
        "factory": "BookColumnFactory", "blender_name": "BookColumnFactory(1)",
        "dimensions": [3.5, 3.5, 3.5], "triangles": 2_000_000,
    })
    assert drop and reason == "decorative_factory_filtered"


def test_fruit_cluster_factory_is_filtered_before_expensive_bake():
    drop, reason = is_small_highpoly_record({
        "kind": "furniture", "semantic_type": "landmark",
        "factory": "FruitFactoryBlackberry", "dimensions": [1.2, 0.9, 0.8],
        "triangles": 40_000,
    })
    assert drop and reason == "pathological_factory_filtered"


def test_non_structural_aquarium_detail_is_filtered_before_strict_bake():
    drop, reason = is_small_highpoly_record({
        "kind": "furniture", "semantic_type": "landmark",
        "factory": "AquariumTankFactory", "dimensions": [0.9, 0.7, 0.8],
        "triangles": 125_000,
    })
    assert drop and reason == "pathological_factory_filtered"


def test_bounded_ceramic_and_cookware_reach_lod_and_bake():
    for factory in ("JarFactory", "PotFactory", "VaseFactory", "BowlFactory", "PlateFactory"):
        drop, reason = is_small_highpoly_record({
            "kind": "furniture", "semantic_type": "prop", "factory": factory,
            "dimensions": [0.25, 0.3, 0.22], "triangles": 275_000,
        })
        assert not drop and reason == "recoverable_pbr_detail"


def test_pathological_pbr_detail_still_drops_at_hard_cap():
    drop, reason = is_small_highpoly_record({
        "kind": "furniture", "semantic_type": "bookstack", "factory": "BookStackFactory",
        "dimensions": [0.3, 0.3, 0.4], "triangles": 750_000,
    })
    assert drop and reason == "decorative_factory_filtered"


def test_real_column_remains_protected():
    drop, reason = is_small_highpoly_record({
        "kind": "furniture", "semantic_type": "structure",
        "factory": "ColumnFactory", "dimensions": [0.18, 0.18, 0.22],
        "triangles": 350_000,
    })
    assert not drop and reason == "protected_structural_token"
