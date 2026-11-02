"""Tag every light in an existing blend with ir_fixture (fixture_tags.apply) and save, for scenes frozen before the tag existed.

  run_bundled_blender.py --background IN.blend --python tools/infinigen/fixture_tags_run.py -- --out OUT.blend

blender_export_scene.py then writes fixture_name / fixture_oid per light, and apps/import_infinigen_scene.py turns them into
metadata.fixture_id (opticalnav sim pairing, 2026-10-23). Writes OUT.blend; never overwrites IN unless OUT == IN.
"""
import argparse, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bpy  # noqa: E402
import fixture_tags  # noqa: E402

ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True)
a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
stats = {}
stats["fixture_tags"] = fixture_tags.apply(stats)
print("FIXTURE_TAGS", stats.get("fixture_tags", stats), flush=True)
bpy.ops.wm.save_as_mainfile(filepath=str(Path(a.out).resolve()), copy=True)
