#!/usr/bin/env python3
"""Join two finalized TextureCan structural registries into one pool.

The environment corpus needs families from both sides and neither has them all.
`texturecan_environment_v1` carries the metal, marble and stone an exterior or a
non-domestic interior is made of; `texturecan_structural_extended_v2` carries
the tile, wood, fabric and concrete a building interior is made of. A concrete
office with a wood floor needs a wall from the second and nothing else does --
so rather than teach the composer to read two registries, the two are joined
once here and it keeps reading one.

Texture directories are **symlinked, not copied**. Between them the two roots
hold several gigabytes of 2K maps, and a copy would be a second sole copy of
the same bytes with no one tracking which is authoritative -- the failure
`_asset_cache` already demonstrates elsewhere in this repo.

Materials present in both are deduplicated on id after checking that they are
in fact the same asset. Fourteen of them overlap and all fourteen agree on
sha256; an id that collides with *different* bytes is a real conflict and this
refuses rather than picking a winner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))

SCHEMA = "robomituba.ir_external_structural_pbr_registry.v1"
#: Directories a material's `maps` and `source_zip` entries are written relative
#: to, with the depth at which their entries are unique. `texturecan/` holds one
#: directory per material, so one level; `source_zips/` holds a `texturecan/`
#: that BOTH registries have, so linking at one level takes the first and hides
#: the second -- which it silently did, leaving 86 of 112 source zips
#: unreachable while every map resolved fine.
LINKED_SUBDIRS = {"texturecan": 1, "source_zips": 2}


def canonical_digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load(root: Path) -> dict:
    payload = json.loads((root / "registry.lock.json").read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise SystemExit(f"{root}: unexpected schema {payload.get('schema')!r}")
    return payload


def link_tree(source_root: Path, destination_root: Path, subdir: str, depth: int,
              linked: set[str]) -> int:
    """Symlink the entries of `subdir` into the merged root at `depth` levels.

    Entries rather than the directory itself, because both sources present the
    same directory names and the merged root needs their union. Descend to the
    level where names are actually unique, or the first source's directory wins
    and the second's contents vanish with no error anywhere.

    Entries already linked from an earlier source are left alone: the duplicate
    check upstream has established they are the same bytes.
    """
    source = source_root / subdir
    if not source.is_dir():
        return 0
    made = 0
    for entry in sorted(source.iterdir()):
        relative = f"{subdir}/{entry.name}"
        if depth > 1 and entry.is_dir():
            made += link_tree(source_root, destination_root, relative, depth - 1, linked)
            continue
        if relative in linked:
            continue
        target = destination_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            linked.add(relative)
            continue
        target.symlink_to(entry.resolve())
        linked.add(relative)
        made += 1
    return made


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--registry", type=Path, action="append", required=True,
                        help="a finalized registry root; repeat, earliest wins on a duplicate id")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--version", default="texturecan_environment_merged_v1")
    args = parser.parse_args()

    if len(args.registry) < 2:
        raise SystemExit("--registry twice or more, or there is nothing to merge")

    materials: dict[str, dict] = {}
    provenance: list[dict] = []
    conflicts: list[str] = []
    for root in args.registry:
        root = root.resolve()
        payload = load(root)
        added = 0
        for record in payload["materials"]:
            identifier = str(record["id"])
            existing = materials.get(identifier)
            if existing is None:
                materials[identifier] = record
                added += 1
                continue
            # Same id from two registries is expected; same id with different
            # bytes is not, and silently keeping one would put a material in the
            # pool whose maps are not the ones its checksum describes.
            if existing.get("sha256") != record.get("sha256"):
                conflicts.append(identifier)
        provenance.append({"root": str(root), "declared": len(payload["materials"]),
                           "new": added, "registry_version": payload.get("registry_version"),
                           "source_staging_digest": payload.get("source_staging_digest")})
        print(f"[merge] {root.name}: {len(payload['materials'])} materials, {added} new", flush=True)

    if conflicts:
        raise SystemExit(f"same id, different sha256: {sorted(conflicts)}")

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    linked: set[str] = set()
    for root in args.registry:
        for subdir, depth in LINKED_SUBDIRS.items():
            made = link_tree(root.resolve(), out, subdir, depth, linked)
            if made:
                print(f"[merge] {subdir}: linked {made} from {root.name}", flush=True)

    ordered = [materials[key] for key in sorted(materials)]
    # Every map path is root-relative and the merged root presents the same two
    # directories, so nothing in a record has to be rewritten. Verify that
    # rather than assume it: a dangling map is a scene that fails at texture
    # load, several minutes into a render.
    # EVERY root-relative path a record carries, not just its maps. A first
    # version checked maps only, they all resolved, and 86 of 112 source zips
    # were dangling behind that clean result -- the check has to cover what it
    # claims to cover or it is just a place the bug is not.
    missing = [f"{record['id']}:{name}"
               for record in ordered
               for name, relative in list((record.get("maps") or {}).items())
               + ([("source_zip", record["source_zip"])] if record.get("source_zip") else [])
               if not (out / relative).exists()]
    if missing:
        raise SystemExit(f"{len(missing)} path(s) unreachable from the merged root, "
                         f"first few: {missing[:5]}")

    payload = {
        "schema": SCHEMA,
        "registry_version": args.version,
        "role_policy": "explicit_approved_roles_v1",
        "provider": "TextureCan",
        "merged_from": provenance,
        "materials": ordered,
    }
    payload["digest"] = canonical_digest({k: v for k, v in payload.items() if k != "digest"})
    (out / "registry.lock.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    from collections import Counter
    families = Counter(record.get("surface_family") or record.get("category") for record in ordered)
    roles = Counter(role for record in ordered for role in record.get("approved_roles") or [])
    print(f"[merge] {len(ordered)} materials -> {out / 'registry.lock.json'}")
    print(f"[merge] families {dict(families)}")
    print(f"[merge] roles {dict(roles)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
