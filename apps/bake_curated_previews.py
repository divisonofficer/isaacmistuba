"""CLI entry: bake the curated material library to PNG.

Usage:

    python apps/bake_curated_previews.py
    python apps/bake_curated_previews.py --force
    python apps/bake_curated_previews.py --only aluminum,glass_clear

Outputs to ``assets/material_previews/curated/{material_id}.png``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from mitsuba_converter.bake_curated_previews import bake_all
from robomituba_bridge import repo_root_from


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=None,
                        help="Repository root. Defaults to auto-detected.")
    parser.add_argument("--size", type=int, default=192,
                        help="PNG side length in pixels (default 192).")
    parser.add_argument("--spp", type=int, default=2048,
                        help="Samples per pixel (default 2048 — matches the on-demand daemon path).")
    parser.add_argument("--force", action="store_true",
                        help="Re-render even when the PNG already exists.")
    parser.add_argument("--only", default=None,
                        help="Comma-separated subset of material_ids to bake.")
    parser.add_argument("--variant", default=None,
                        help="Override Mitsuba variant (e.g. scalar_rgb to bypass OptiX).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    repo_root: Path = repo_root_from(args.repo_root)
    only = [s.strip() for s in args.only.split(",")] if args.only else None
    statuses = bake_all(repo_root, size=args.size, spp=args.spp, force=args.force, only=only, variant=args.variant)

    n_baked = sum(1 for v in statuses.values() if v == "baked")
    n_skipped = sum(1 for v in statuses.values() if v == "skipped")
    n_error = sum(1 for v in statuses.values() if v == "error")
    print(f"\nDone. baked={n_baked} skipped={n_skipped} errors={n_error}")
    return 1 if n_error else 0


if __name__ == "__main__":
    sys.exit(main())
