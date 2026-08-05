#!/usr/bin/env python3
"""Reclaim space in out/bridge_jobs_archive by dropping duplicated rasters.

Context
-------
``apps/archive_completed_bridge_jobs.py`` MOVES completed OpticalNav jobs out of
the daemon's scan path. It moves the whole job dir, so the archive holds both

  * sole-copy provenance - ``requests/<frame>.json`` (the re-render input) and
    ``job_status.json``; and
  * heavy rasters under ``observations/`` that were already copied into
    ``out/opticalnav/<proj>/scenes/<scene>/observations/<vp>/<heading>/``.

Deleting the archive wholesale loses the sole-copy provenance, and a 40-job
sample showed the duplication premise only partly holds: 10% of archived jobs
have no dataset destination at all, and the dataset copy routinely lacks
``manifest.json`` / ``render_timing.json`` / ``rgb_raw.npz`` (and occasionally
``rgb.exr``). The archiver's own check is permissive - it accepts rgb.png OR
rgb.exr - which is why those gaps slipped through.

What this does
--------------
Per archived job, delete ONLY the raster files that are provably duplicated:

    rgb.png, rgb.exr   deleted only when BOTH exist at the dataset destination
    rgb_raw.npz        deleted with them (float32 duplicate of the EXR, per
                       the repo's bridge_jobs layout notes)

Always kept: ``requests/``, ``job_status.json``, ``render_progress.log``, and
``observations/**/manifest.json`` + ``render_timing.json`` - the pose,
intrinsics and timing metadata, which the consolidated dataset does NOT carry
and which costs kilobytes.

A job is skipped untouched when coords cannot be read, the destination is
missing, or either raster is absent there. Default is a dry run.

Usage:
    python apps/migrations/prune_archived_bridge_job_rasters.py            # dry run
    python apps/migrations/prune_archived_bridge_job_rasters.py --apply
    python apps/migrations/prune_archived_bridge_job_rasters.py --report r.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RASTERS = ("rgb.png", "rgb.exr", "rgb_raw.npz")
# Duplication is only proven when both of these exist at the destination; the
# npz rides along because it is a float32 restatement of the EXR.
REQUIRED_AT_DEST = ("rgb.png", "rgb.exr")


def load_archiver():
    """Reuse the archiver's coord reader so both tools agree on job identity."""
    path = REPO_ROOT / "apps/archive_completed_bridge_jobs.py"
    spec = importlib.util.spec_from_file_location("archive_completed_bridge_jobs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dataset_dest(coords: dict) -> Path:
    return (REPO_ROOT / "out" / "opticalnav" / coords["project_id"] / "scenes"
            / coords["scene_id"] / "observations" / coords["vp_id"] / coords["heading_id"])


def dest_has_rasters(dest: Path) -> bool:
    """Strict check: every required raster present, anywhere under the dest."""
    if not dest.is_dir():
        return False
    try:
        names = {p.name for p in dest.rglob("*") if p.is_file()}
    except OSError:
        return False
    return all(name in names for name in REQUIRED_AT_DEST)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--archive-dir", default="out/bridge_jobs_archive")
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", type=Path, help="per-job JSONL report; resumed if it exists")
    ap.add_argument("--progress-every", type=int, default=250)
    args = ap.parse_args()

    archiver = load_archiver()
    root = REPO_ROOT / args.archive_dir
    if not root.is_dir():
        raise SystemExit(f"no archive dir: {root}")

    jobs = sorted(p for p in root.iterdir() if p.is_dir())
    if args.limit:
        jobs = jobs[: args.limit]

    # The report is streamed as JSONL and flushed per job: a 7,692-job pass over
    # CIFS can be interrupted, and a partial record is still a usable audit trail.
    # Already-decided jobs are skipped on restart, so the pass is resumable.
    done: set[str] = set()
    report_handle = None
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        if args.report.exists():
            for line in args.report.read_text(encoding="utf-8").splitlines():
                try:
                    done.add(json.loads(line)["job"])
                except Exception:
                    pass
            print(f"resuming: {len(done)} jobs already recorded")
        report_handle = args.report.open("a", encoding="utf-8")

    verdicts = Counter()
    freed = 0
    kept = 0
    rows = []

    def record(row: dict) -> None:
        rows.append(row)
        if report_handle is not None:
            report_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            report_handle.flush()

    for index, job in enumerate(jobs, 1):
        if job.name in done:
            continue
        coords = archiver._opticalnav_coords(job)
        if not coords:
            verdicts["skip_no_coords"] += 1
            record({"job": job.name, "verdict": "skip_no_coords"})
            continue
        dest = dataset_dest(coords)
        if not dest.is_dir():
            verdicts["skip_no_dataset_dir"] += 1
            record({"job": job.name, "verdict": "skip_no_dataset_dir", "dest": str(dest)})
            continue
        if not dest_has_rasters(dest):
            verdicts["skip_dataset_incomplete"] += 1
            record({"job": job.name, "verdict": "skip_dataset_incomplete", "dest": str(dest)})
            continue

        targets = [p for p in (job / "observations").rglob("*")
                   if p.is_file() and p.name in RASTERS]
        size = 0
        for path in targets:
            try:
                size += path.stat().st_size
            except OSError:
                pass
        if args.apply:
            for path in targets:
                try:
                    path.unlink()
                except OSError as exc:
                    print(f"[warn] {path}: {exc}", file=sys.stderr)
        verdicts["pruned" if args.apply else "would_prune"] += 1
        freed += size
        record({"job": job.name, "verdict": "pruned" if args.apply else "would_prune",
                "files": len(targets), "bytes": size})

        if args.progress_every and index % args.progress_every == 0:
            print(f"  [{index}/{len(jobs)}] freed so far {freed / 2**30:.2f} GB", flush=True)

    for row in rows:
        if row["verdict"].startswith("skip"):
            kept += 1

    print(f"\narchive     : {root}")
    print(f"jobs        : {len(jobs)}")
    for verdict, count in sorted(verdicts.items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:26s} {count}")
    print(f"{'freed' if args.apply else 'would free'}: {freed / 2**30:.2f} GB")
    print(f"untouched jobs (kept whole): {kept}")
    if not args.apply:
        print("\ndry run - nothing deleted. re-run with --apply")
    if report_handle is not None:
        report_handle.close()
        print(f"report -> {args.report} (JSONL, {len(rows)} rows this pass)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
