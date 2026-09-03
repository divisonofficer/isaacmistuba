#!/usr/bin/env python3
"""Retire rendered IR datasets that a re-render has superseded or replaced.

Deleting rendered frames is not reversible, so this prints what it would remove
and why, and does nothing until the operator types the confirmation.  Nothing is
removed on a dry run, which is the default.

Three outcomes, decided per scene:

  superseded   a v5 re-render of this scene already exists, so the older render
               is dead weight -- delete it.
  requeue      no re-render yet, but the Stage 1 geometry bake survives, so the
               scene can be re-rendered cheaply -- keep it and queue it.
  protected    no Stage 1 bake either, but the render carries far more smooth
               surface than the corpus average, so it survives on content alone.
  discard      no re-render, no Stage 1 bake, and nothing worth keeping in the
               pixels -- delete it.

Stage 1 bakes are never touched.  They are the expensive artifact and the whole
reason a scene can be re-rendered at all; ``--prune-pipeline`` removes the
pipeline directory for discarded scenes only, and even then leaves any
``ir_geometry`` it finds.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BEAN = Path("/bean/ir_dataset")
WORK = Path("/bean/ir_dataset_work")
PIPELINE = WORK / ".pipeline"

SUPERSEDED, REQUEUE, DISCARD = "superseded", "requeue", "discard"
PROTECTED = "protected"
#: A scene with this much smooth surface is where a controlled NIR highlight can
#: actually appear.  Across the measured corpus most scenes sit under 5%, so the
#: handful above this carry nearly all of the cue the dataset exists to provide.
#: Having no Stage 1 bake makes such a scene expensive to replace, not worthless
#: -- so it is kept as a survival candidate rather than deleted.
RICH_SPECULAR = 10.0
CONFIRM = {"예", "yes", "y"}


def disk_bytes(path: Path) -> int:
    """du is dramatically faster here than walking the tree in Python."""
    try:
        out = subprocess.run(["du", "-sb", str(path)], capture_output=True,
                             text=True, timeout=120)
        return int(out.stdout.split()[0]) if out.returncode == 0 and out.stdout else 0
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return 0


def frame_count(path: Path) -> int:
    index = path / "index.jsonl"
    try:
        return sum(1 for line in index.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


#: Suffixes a dataset picks up without becoming a different render: a contract
#: re-publish, or a storage-profile variant.  The Stage 1 bake lives under the
#: name before them, so a lookup has to try the stripped form as well.
VARIANT_SUFFIX = re.compile(r"(__diffuse_transport_v3(_v2)?|__core_half_exr_v[12]|__pbr_v[0-9]+)+$")


def stage1_source(name: str) -> str | None:
    """The dataset whose Stage 1 bake this one can be re-rendered from."""
    candidates = [name]
    stripped = VARIANT_SUFFIX.sub("", name)
    if stripped != name:
        candidates.append(stripped)
    for candidate in candidates:
        for base in (PIPELINE / candidate, BEAN / candidate, WORK / candidate):
            if (base / "ir_geometry" / "ir_geometry_profile.json").is_file():
                return candidate
            if base.is_dir() and next(base.glob("attempts/**/ir_geometry/ir_geometry_profile.json"), None):
                return candidate
    return None


def dataset_roots() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for base in (BEAN, WORK):
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if (entry / "index.jsonl").is_file():
                found.setdefault(entry.name, entry)
    return found


def classify(plan: dict, roots: dict[str, Path], stats: dict, *, sizes: bool,
             protect_specular: float = RICH_SPECULAR) -> list[dict]:
    """Assign every named dataset an outcome and the reason for it."""
    raw = plan.get("superseded_by_rerender") or {}
    # A list means "trust me"; a mapping of old -> replacement lets the script
    # check the replacement actually rendered.  Retiring an original because a
    # replacement was *queued* loses both if that queue run fails.
    superseded = raw if isinstance(raw, dict) else {name: None for name in raw}
    rows = []
    for name, path in roots.items():
        source = stage1_source(name)
        specular = round(stats.get(name, {}).get("specular_share", -0.01) * 100, 1)
        if name in superseded:
            replacement = superseded[name]
            done = frame_count(roots[replacement]) if replacement in roots else 0
            if replacement is not None and done <= 0:
                outcome = REQUEUE
                reason = (f"replacement {replacement} has not rendered yet "
                          "-- retiring this now would lose both")
            else:
                outcome = SUPERSEDED
                reason = ("a newer re-render of this scene already exists"
                          + (f" ({replacement}, {done:,} frames)" if replacement else ""))
        elif source:
            outcome = REQUEUE
            reason = ("Stage 1 bake survives, so it can be re-rendered cheaply"
                      + ("" if source == name else f" (bake under {source})"))
        elif specular >= protect_specular:
            # Nothing here can be re-rendered, but almost nothing else in the
            # corpus carries this much smooth surface.  Replacing it means
            # generating the scene again, so it survives on its content alone.
            outcome = PROTECTED
            reason = (f"no Stage 1 bake, but {specular:.1f}% smooth surface -- too much of the "
                      "cue to throw away when replacing it means regenerating the scene")
        else:
            outcome, reason = DISCARD, "no re-render and no Stage 1 bake; nothing here is reusable"
        rows.append({"scene": name, "path": str(path), "outcome": outcome, "reason": reason,
                     "stage1_source": source, "frames": frame_count(path), "bytes": 0,
                     "specular": specular})
    if sizes:
        # du on this storage takes seconds per dataset and is pure I/O wait, so
        # it is worth running the whole inventory concurrently.
        with ThreadPoolExecutor(max_workers=16) as pool:
            for row, total in zip(rows, pool.map(lambda r: disk_bytes(Path(r["path"])), rows)):
                row["bytes"] = total
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", type=Path, required=True,
                        help='JSON with {"superseded_by_rerender": [dataset names]}')
    parser.add_argument("--delete", action="store_true",
                        help="actually delete; without it nothing is removed")
    parser.add_argument("--outcome", action="append", choices=(SUPERSEDED, DISCARD),
                        help="restrict to one outcome (repeatable); requeue is never deleted")
    parser.add_argument("--prune-pipeline", action="store_true",
                        help="also remove the pipeline directory of discarded scenes, "
                             "keeping any ir_geometry inside it")
    parser.add_argument("--manifest", type=Path, default=None,
                        help="where to record what was removed")
    parser.add_argument("--yes", action="store_true",
                        help="skip the prompt (for non-interactive use); still needs --delete")
    parser.add_argument("--stats", type=Path, default=None,
                        help="scene_qa.json, so the listing can show how much smooth "
                             "surface each dataset carries")
    parser.add_argument("--no-size", action="store_true",
                        help="skip the disk measurement, which is slow on network storage")
    parser.add_argument("--protect-specular", type=float, default=RICH_SPECULAR,
                        help="keep an otherwise-discardable dataset whose smooth surface "
                             f"reaches this percentage (default {RICH_SPECULAR:g}; "
                             "0 disables the protection)")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    stats = {}
    if args.stats and args.stats.is_file():
        stats = json.loads(args.stats.read_text(encoding="utf-8"))
    rows = classify(plan, dataset_roots(), stats, sizes=not args.no_size,
                    protect_specular=args.protect_specular if args.protect_specular > 0 else 1e9)
    wanted = set(args.outcome or (SUPERSEDED, DISCARD))
    targets = [r for r in rows if r["outcome"] in wanted]

    VERB = {REQUEUE: "keep and queue", PROTECTED: "keep as a survival candidate"}
    for outcome in (SUPERSEDED, REQUEUE, PROTECTED, DISCARD):
        group = [r for r in rows if r["outcome"] == outcome]
        if not group:
            continue
        total = sum(r["bytes"] for r in group)
        print(f"\n=== {outcome}  ({VERB.get(outcome, 'DELETE')})  {len(group)} datasets, "
              f"{sum(r['frames'] for r in group):,} frames, {total/1e9:.1f} GB")
        print(f"    reason: {group[0]['reason']}")
        for r in sorted(group, key=lambda x: -x["specular"]):
            spec = f"spec {r['specular']:5.1f}%" if r["specular"] >= 0 else "spec     ?"
            print(f"      {r['bytes']/1e9:7.2f} GB  {r['frames']:6,d} frames  "
                  f"{spec}  {r['scene']}")

    if not targets:
        print("\nnothing selected for deletion.")
        return 0
    freed = sum(r["bytes"] for r in targets)
    print(f"\n{'-'*72}")
    print(f"selected for deletion: {len(targets)} datasets, "
          f"{sum(r['frames'] for r in targets):,} frames, {freed/1e9:.1f} GB")
    print("Stage 1 bakes are not touched.")
    protected = [r for r in rows if r["outcome"] == PROTECTED]
    if protected:
        print(f"{len(protected)} datasets are held back on smooth-surface content alone "
              f"(>= {args.protect_specular:g}%);")
        print("pass --protect-specular 0 to include them.")
    rich = [r for r in targets if r["specular"] >= RICH_SPECULAR]
    if rich:
        print(f"\n  WARNING: {len(rich)} selected datasets still carry >= {RICH_SPECULAR:.0f}% "
              "smooth surface,")
        print("  which is the cue this dataset exists to capture:")
        for r in sorted(rich, key=lambda x: -x["specular"]):
            print(f"      spec {r['specular']:5.1f}%  {r['outcome']:10} {r['scene']}")

    if not args.delete:
        print("\ndry run -- nothing was deleted.  Re-run with --delete to act on this.")
        return 0
    if not args.yes:
        print("\n위 데이터셋을 삭제합니다. 동의하십니까?  (예 / yes 를 입력하면 삭제)")
        try:
            answer = input("> ").strip()
        except EOFError:
            answer = ""
        if answer.lower() not in CONFIRM:
            print("취소했습니다. 아무것도 삭제하지 않았습니다.")
            return 1

    removed = []
    for r in targets:
        path = Path(r["path"])
        try:
            shutil.rmtree(path)
            removed.append({**r, "pipeline_pruned": False})
            print(f"  removed {path}")
        except OSError as exc:
            print(f"  FAILED  {path}: {exc}", file=sys.stderr)
            continue
        if args.prune_pipeline and r["outcome"] == DISCARD:
            pipe = PIPELINE / r["scene"]
            if pipe.is_dir() and not next(pipe.glob("**/ir_geometry"), None):
                try:
                    shutil.rmtree(pipe)
                    removed[-1]["pipeline_pruned"] = True
                    print(f"  removed {pipe}")
                except OSError as exc:
                    print(f"  FAILED  {pipe}: {exc}", file=sys.stderr)

    manifest = args.manifest or Path("ir_dataset_prune_manifest.json")
    manifest.write_text(json.dumps({
        "schema": "robomituba.ir_dataset_prune.v1",
        "removed": len(removed), "freed_bytes": sum(r["bytes"] for r in removed),
        "datasets": removed}, indent=2), encoding="utf-8")
    print(f"\nremoved {len(removed)} datasets, freed "
          f"{sum(r['bytes'] for r in removed)/1e9:.1f} GB")
    print(f"manifest -> {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
