from collections import Counter
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.migrations.prune_opticalnav_scene_decor import plan_prune


def test_factory_prune_stops_at_target_and_keeps_critical_objects() -> None:
    objects = [
        {"id": "trinket", "metadata": {"factory": "NatureShelfTrinketsFactory"}},
        {"id": "books", "metadata": {"factory": "BookStackFactory"}},
        {"id": "column", "metadata": {"factory": "BookColumnFactory"}},
        {
            "id": "critical_books", "metadata": {"factory": "BookStackFactory"},
            "navigation": {"goal_candidate": True},
        },
    ]
    plan = plan_prune(
        objects, Counter({"trinket": 25, "books": 20, "column": 10, "critical_books": 5}),
        target_shapes=20,
    )
    assert plan["removed_factories"] == ["NatureShelfTrinketsFactory", "BookStackFactory"]
    assert plan["result_shapes"] == 15
    assert "critical_books" not in plan["removed_object_ids"]
