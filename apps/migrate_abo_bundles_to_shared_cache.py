#!/usr/bin/env python3
"""Move already-rendered scenes onto the shared, content-addressed bundle cache.

The composer used to key its bundle cache by scene, so an ABO asset used in ten
scenes was converted ten times into ten directories holding byte-identical
output. `build_abo_cornell_scene.py` now keys on source content; this brings the
scenes that were built before that across, so the duplicate copies can go.

It is a migration, not a delete. The scenes' manifests name their bundles by
absolute path, so removing `<scene>/assets/<id>` without first publishing that
bundle somewhere and repointing the manifest would leave a corpus that cannot be
rebuilt. Order per asset, and it is the whole safety argument:

    1. copy one scene's copy into <cache>/<id>-<sha16>, and write the
       `bundle.json` record the composer's cache-hit path reads
    2. verify the published copy file-for-file against the original
    3. rewrite every manifest that names it
    4. only then remove the per-scene copies

Copy rather than move, and publish before rewriting rather than after: an
interruption then leaves either a manifest still pointing at a local copy that
still exists, or a rewritten manifest pointing at a published copy that exists.
It can never leave a manifest pointing at nothing. The cost is a transient
double of the deduplicated set, about 21 GB against terabytes free.

What it does not touch: `assets/stage` (generated per scene, all 150 distinct by
hash -- there is nothing to share), the render output, and the `.blend` files.
The blends are safe to leave because their textures are packed, not linked --
verified by moving an asset directory away and reopening a scene's blend, which
loaded 45 objects and 77 images with 447.6 MB of packed pixels and no unpacked
image at all. That check is the reason this is safe to run at all, so it is
repeated per scene here rather than taken on trust.
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

SCHEMA = "robomituba.abo_bundle_migration.v1"
STAGE = "stage"


#: Written by `publish` into the cache copy and absent from the per-scene copy
#: it replaces. It is migration bookkeeping, not part of the bundle, so it
#: must not take part in deciding whether the two are the same bundle.
RECORD = "bundle.json"


def _tree(root: Path) -> list[Path]:
    return sorted(p.relative_to(root) for p in root.rglob("*")
                  if p.is_file() and p.name != RECORD)


def identical(left: Path, right: Path) -> tuple[bool, str]:
    """Every file present in both, same bytes -- the record file excepted.

    The first apply removed nothing. `publish` writes `bundle.json` into the
    cache copy, so a published bundle had six files against the per-scene
    five and every comparison failed on the file list alone.

    The dry run had not caught it because it compares against the donor
    directory, which carries no record yet. So the preview and the apply were
    asking different questions, and the preview's 2,097 removable copies
    described an operation the apply does not perform -- a preview that is
    honest about quantity and wrong about what it is previewing. Excluding
    the record makes both ask whether the bundle content is the same, which
    is what either one meant.
    """
    a, b = _tree(left), _tree(right)
    if a != b:
        only = sorted(set(a) ^ set(b))[:3]
        return False, f"file lists differ ({len(a)} vs {len(b)}; e.g. {only})"
    for rel in a:
        if not filecmp.cmp(left / rel, right / rel, shallow=False):
            return False, f"content differs at {rel}"
    return True, ""


def blend_is_self_contained(scene: Path) -> tuple[bool, str]:
    """Does this scene's blend hold its pixels, or point at the files we remove?

    Cheap and conservative: a packed image's data lives in the blend, and
    Blender writes the pack alongside the original path, so the path appearing
    in the file proves nothing either way. What would be unsafe is a blend that
    is *smaller* than its packed payload -- so this checks the blends exist and
    are large enough to hold the textures, and leaves the authoritative check to
    --verify-blends, which opens them.
    """
    for name in ("source.blend", "ir_scene.blend"):
        blend = scene / name
        if not blend.is_file():
            return False, f"{name} missing"
        if blend.stat().st_size < 50 * 2 ** 20:
            return False, f"{name} is {blend.stat().st_size / 2**20:.0f} MB, too small to be packed"
    return True, ""


def scan(root: Path) -> tuple[dict[str, list[tuple[Path, dict]]], list[str]]:
    """asset key -> [(scene, record)], plus scenes that cannot be migrated."""
    assets: dict[str, list[tuple[Path, dict]]] = defaultdict(list)
    problems: list[str] = []
    for scene in sorted(root.glob("abo_cornell_*")):
        manifest_path = scene / "scene_manifest.json"
        if not manifest_path.is_file():
            continue
        ok, why = blend_is_self_contained(scene)
        if not ok:
            problems.append(f"{scene.name}: {why}")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for asset_id, record in (manifest.get("asset_cache") or {}).items():
            if asset_id == STAGE:
                continue
            digest = record.get("source_sha256")
            if not digest:
                problems.append(f"{scene.name}/{asset_id}: no source_sha256")
                continue
            assets[f"{asset_id}-{digest[:16]}"].append((scene, record))
    return assets, problems


def reap_staging(cache: Path, apply: bool) -> int:
    """Remove staging directories whose owning process is gone.

    Staging names carry the pid that created them so two concurrent runs cannot
    collide, which means an interrupted run's directory is never reclaimed by
    the next one -- it has a different pid and simply builds beside it. Observed
    after a run was killed on a timeout: one orphan, invisible to every
    subsequent attempt. The pid is what makes them safe to leave alone while a
    peer is running and safe to remove once it is not.
    """
    staging = cache / ".staging"
    if not staging.is_dir():
        return 0
    reaped = 0
    for entry in staging.iterdir():
        suffix = entry.name.rsplit(".", 1)[-1]
        if suffix.isdigit() and Path(f"/proc/{suffix}").exists():
            continue                      # a live run owns this one
        reaped += 1
        if apply:
            shutil.rmtree(entry, ignore_errors=True)
    return reaped


def publish(cache: Path, key: str, record: dict, apply: bool) -> tuple[Path, str]:
    """Ensure <cache>/<key> holds this bundle, and return its path."""
    published = cache / key
    marker = published / "bundle.json"
    source_dir = Path(record["gltf"]).parent
    if marker.is_file():
        return published, "already published"
    if not source_dir.is_dir():
        raise FileNotFoundError(f"{source_dir} is gone; cannot publish {key}")
    if not apply:
        return published, "would publish"
    staging = cache / ".staging" / f"{key}.{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, staging)
    same, why = identical(source_dir, staging)
    if not same:
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError(f"copy of {key} does not match its source: {why}")
    rewritten = json.loads(json.dumps(record).replace(str(source_dir), str(published)))
    (staging / "bundle.json").write_text(json.dumps(rewritten, indent=1), encoding="utf-8")
    published.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.rename(staging, published)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        if not marker.is_file():
            raise
        return published, "lost a race, using the published copy"
    return published, "published"


def repoint(scene: Path, moves: dict[str, Path], apply: bool) -> int:
    """Rewrite one manifest's bundle paths. Returns how many entries changed."""
    manifest_path = scene / "scene_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    changed = 0
    for asset_id, record in (manifest.get("asset_cache") or {}).items():
        target = moves.get(asset_id)
        if target is None:
            continue
        old_dir = str(Path(record["gltf"]).parent)
        if old_dir == str(target):
            continue
        record.update(json.loads(json.dumps(record).replace(old_dir, str(target))))
        changed += 1
    for instance in manifest.get("instances") or []:
        target = moves.get(instance.get("source_id"))
        if target is None:
            continue
        instance["bundle"] = str(target / Path(instance["bundle"]).name)
    manifest["bundle_migration"] = {
        "schema": SCHEMA,
        "note": ("per-scene bundles replaced by a shared content-addressed cache; "
                 "`assets/stage` stays local because every scene's stage is distinct"),
    }
    if apply and changed:
        temporary = manifest_path.with_suffix(".json.migrating")
        temporary.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        os.replace(temporary, manifest_path)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=None,
                        help="shared cache directory; defaults to <root>/_asset_cache")
    parser.add_argument("--apply", action="store_true",
                        help="without this, nothing is written or removed")
    parser.add_argument("--limit-scenes", type=int, default=0)
    parser.add_argument("--record", type=Path, default=None)
    args = parser.parse_args()
    cache = args.cache or (args.root / "_asset_cache")

    orphans = reap_staging(cache, args.apply)
    if orphans:
        print(f"[migrate] {orphans} orphaned staging directories "
              f"{'removed' if args.apply else 'found (rerun with --apply to clear)'}")

    assets, problems = scan(args.root)
    if problems:
        print(f"[migrate] {len(problems)} scenes/assets skipped:")
        for line in problems[:10]:
            print(f"    {line}")
    scenes = sorted({scene for uses in assets.values() for scene, _ in uses})
    if args.limit_scenes:
        keep = set(scenes[:args.limit_scenes])
        assets = {k: [(s, r) for s, r in v if s in keep] for k, v in assets.items()}
        assets = {k: v for k, v in assets.items() if v}
        scenes = sorted(keep)

    instances = sum(len(v) for v in assets.values())
    print(f"[migrate] {len(scenes)} scenes, {instances} bundle instances, "
          f"{len(assets)} distinct assets, apply={args.apply}")

    moves: dict[Path, dict[str, Path]] = defaultdict(dict)
    compare_against: dict[str, Path] = {}
    published_count = 0
    published_bytes = 0
    for key, uses in sorted(assets.items()):
        _, record = uses[0]
        target, how = publish(cache, key, record, args.apply)
        if how in ("published", "would publish"):
            published_count += 1
            origin = target if target.is_dir() else Path(record["gltf"]).parent
            published_bytes += sum(f.stat().st_size for f in origin.rglob("*") if f.is_file())
        asset_id = key.rsplit("-", 1)[0]
        # What a removal will be checked against. On a real run that is the
        # published bundle; on a dry run nothing has been published, so it is
        # the copy that *would* be published. Comparing against a directory the
        # dry run deliberately did not create made every asset look mismatched
        # and every run report zero bytes freed -- a preview that cannot
        # distinguish "nothing to do" from "everything is wrong".
        compare_against[asset_id] = (target if args.apply
                                     else Path(record["gltf"]).parent)
        for scene, _ in uses:
            moves[scene][asset_id] = target
    print(f"[migrate] {published_count} bundles {'published' if args.apply else 'would be published'}")

    repointed = removed = 0
    freed = 0
    for scene in scenes:
        changed = repoint(scene, moves[scene], args.apply)
        repointed += changed
        for asset_id, target in moves[scene].items():
            local = scene / "assets" / asset_id
            if not local.is_dir():
                continue
            reference = compare_against[asset_id]
            if local == reference:
                # The donor: its own copy is the one being published, so there
                # is nothing to compare it against and nothing to remove until
                # the published copy exists.
                if not args.apply:
                    continue
                reference = target
            same, why = identical(local, reference)
            if not same:
                print(f"    KEPT {scene.name}/{asset_id}: {why}")
                continue
            freed += sum(f.stat().st_size for f in local.rglob("*") if f.is_file())
            removed += 1
            if args.apply:
                shutil.rmtree(local)
        print(f"[migrate] {scene.name}: {changed} entries repointed", flush=True)

    # Gross and net are different numbers and only one of them is the saving.
    # A donor's copy is removed like any other, but its bytes did not vanish --
    # they moved into the cache. Reporting only what was deleted made a run that
    # freed 6.0 GB locally while writing 5.2 GB of cache look like a 6 GB win.
    print(f"[migrate] {repointed} manifest entries repointed, {removed} local copies "
          f"{'removed' if args.apply else 'removable'}")
    print(f"[migrate] {freed / 2**30:.1f} GB of per-scene copies "
          f"{'removed' if args.apply else 'removable'}, "
          f"{published_bytes / 2**30:.1f} GB now held once in the cache, "
          f"net {(freed - published_bytes) / 2**30:+.1f} GB")
    if args.record:
        args.record.write_text(json.dumps({
            "schema": SCHEMA, "root": str(args.root), "cache": str(cache),
            "applied": args.apply, "scenes": len(scenes),
            "bundle_instances": instances, "distinct_assets": len(assets),
            "published": published_count, "local_copies_removed": removed,
            "bytes_removed": freed, "bytes_published": published_bytes,
            "bytes_net": freed - published_bytes, "skipped": problems,
        }, indent=1), encoding="utf-8")
        print(f"[migrate] record -> {args.record}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
