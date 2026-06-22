#!/usr/bin/env python3
"""Archive completed OpticalNav bridge jobs out of the daemon's scan path.

The render daemon re-scans EVERY ``out/bridge_jobs/<job>/`` on startup and on
(almost) every control-plane request — unconditionally globbing
``*/job_status.json`` and the nested ``*/observations/*/manifest.json`` and
deserializing all of them (no status filter, 2-3s cache TTL). On the CIFS mount
with thousands of accumulated jobs this costs minutes per refresh.

A completed job is staging: ``_mark_succeeded`` already copies its PNG + EXR
observations into the consolidated dataset at
``out/opticalnav/<proj>/scenes/<scene>/observations/<vp>/<heading>/``. So once
that copy is confirmed on disk, the job dir is redundant for the daemon and can
be moved out of the glob path. We MOVE (not delete) so the sole-copy
``requests/<frame>.json`` (re-render input) and ``job_status.json`` survive.

Safety: only ``succeeded`` jobs whose dataset destination is verified to exist
(``rgb.png`` or ``sensors/<cam>/rgb.exr``) are eligible. Anything unverified,
non-terminal, or non-OpticalNav is left untouched. Default is ``--dry-run``.

Usage:
    python apps/archive_completed_bridge_jobs.py                 # dry-run report
    python apps/archive_completed_bridge_jobs.py --apply         # move eligible
    python apps/archive_completed_bridge_jobs.py --apply --limit 50
    python apps/archive_completed_bridge_jobs.py --scene cglab_conference_room --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_NON_TERMINAL = {"running", "queued", "pending"}
_TERMINAL_OK = {"succeeded"}  # extended with failed/cancelled via --include-failed


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _job_status(job_dir: Path) -> str | None:
    data = _read_json(job_dir / "job_status.json")
    if not isinstance(data, dict):
        return None
    status = data.get("status")
    return str(status) if status is not None else None


def _opticalnav_coords(job_dir: Path) -> dict | None:
    """Read (project, scene, vp, heading, frame) from the saved RenderRequest."""
    req_dir = job_dir / "requests"
    if not req_dir.is_dir():
        return None
    try:
        req_files = sorted(req_dir.glob("*.json"))
    except OSError:
        return None
    for rp in req_files:
        req = _read_json(rp)
        if not isinstance(req, dict):
            continue
        ex = req.get("extras") or {}
        proj = ex.get("opticalnav_project_id")
        scene = ex.get("opticalnav_scene_id")
        vp = ex.get("opticalnav_vp_id")
        heading = ex.get("opticalnav_heading_id")
        if proj and scene and vp and heading:
            return {"project_id": str(proj), "scene_id": str(scene),
                    "vp_id": str(vp), "heading_id": str(heading)}
    return None


def _dataset_copy_present(coords: dict) -> bool:
    """True when the consolidated dataset observation for these coords exists.

    Mirrors the destination written by render_daemon._opticalnav_copy_observation_rgb:
    out/opticalnav/<proj>/scenes/<scene>/observations/<vp>/<heading>/ with rgb.png
    (UI preview) or sensors/<cam>/rgb.exr (HDR raster).
    """
    dest = (REPO_ROOT / "out" / "opticalnav" / coords["project_id"] /
            "scenes" / coords["scene_id"] / "observations" /
            coords["vp_id"] / coords["heading_id"])
    if not dest.is_dir():
        return False
    if (dest / "rgb.png").exists():
        return True
    sensors = dest / "sensors"
    if sensors.is_dir():
        try:
            for cam in sensors.iterdir():
                if cam.is_dir() and (cam / "rgb.exr").exists():
                    return True
        except OSError:
            return False
    return False


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Report only, move nothing (this is the default).")
    ap.add_argument("--apply", action="store_true",
                    help="Actually move eligible jobs (default: dry-run).")
    ap.add_argument("--delete", action="store_true",
                    help="DANGER: delete instead of move. Implies --apply. Loses requests/status.")
    ap.add_argument("--include-failed", action="store_true",
                    help="Also archive failed/cancelled jobs (no dataset-copy check for these).")
    ap.add_argument("--scene", default=None, help="Only consider jobs for this OpticalNav scene id.")
    ap.add_argument("--limit", type=int, default=0, help="Process at most N eligible jobs (0 = all).")
    ap.add_argument("--archive-dir", default="out/bridge_jobs_archive",
                    help="Destination root for moved jobs (repo-relative).")
    ap.add_argument("--size", action="store_true",
                    help="Account moved bytes via rglob (HEAVY on CIFS; off by default).")
    ap.add_argument("--max-scan", type=int, default=0,
                    help="Examine at most N job dirs this run, then stop (0 = all). "
                         "Use to bound I/O per invocation on slow mounts; re-run to continue.")
    ap.add_argument("--throttle-ms", type=float, default=8.0,
                    help="Sleep this many ms every --throttle-every jobs to avoid I/O storms "
                         "that can hang/OOM a CIFS-mounted WSL. Set 0 to disable.")
    ap.add_argument("--throttle-every", type=int, default=1,
                    help="Apply the throttle sleep once per this many jobs (default: every job).")
    args = ap.parse_args()

    apply = args.apply or args.delete
    jobs_root = REPO_ROOT / "out" / "bridge_jobs"
    if not jobs_root.is_dir():
        print(f"[archive] no bridge_jobs dir at {jobs_root}", file=sys.stderr)
        return
    archive_root = (REPO_ROOT / args.archive_dir) if not Path(args.archive_dir).is_absolute() else Path(args.archive_dir)

    terminal_ok = set(_TERMINAL_OK)
    if args.include_failed:
        terminal_ok |= {"failed", "cancelled"}

    print(f"[archive] scanning {jobs_root} (apply={apply} delete={args.delete})…", flush=True)
    t0 = time.time()

    counts = {"scanned": 0, "eligible": 0, "archived": 0}
    skipped: dict[str, int] = {}
    bytes_eligible = 0
    eligible_samples: list[str] = []

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    try:
        job_dirs = sorted(p for p in jobs_root.iterdir() if p.is_dir())
    except OSError as exc:
        print(f"[archive] cannot list {jobs_root}: {exc}", file=sys.stderr)
        return

    throttle_s = max(0.0, args.throttle_ms) / 1000.0
    throttle_every = max(1, args.throttle_every)
    reached_end = True

    for idx, job_dir in enumerate(job_dirs):
        if args.max_scan and counts["scanned"] >= args.max_scan:
            reached_end = False
            print(f"[archive] hit --max-scan {args.max_scan}; stopping "
                  f"(re-run to continue — moved jobs leave the scan path).", flush=True)
            break
        # Pace CIFS I/O so a tight stat/open burst can't hang/OOM WSL.
        if throttle_s and (idx % throttle_every == 0):
            time.sleep(throttle_s)
        counts["scanned"] += 1
        if counts["scanned"] % 500 == 0:
            print(f"[archive]   …scanned {counts['scanned']}/{len(job_dirs)} "
                  f"(eligible={counts['eligible']})", flush=True)

        status = _job_status(job_dir)
        if status is None:
            skip("no_status"); continue
        if status in _NON_TERMINAL:
            skip(f"non_terminal:{status}"); continue
        if status not in terminal_ok:
            skip(f"status:{status}"); continue

        coords = _opticalnav_coords(job_dir)
        if status == "succeeded":
            if coords is None:
                skip("no_opticalnav_coords"); continue
            if args.scene and coords["scene_id"] != args.scene:
                skip("other_scene"); continue
            if not _dataset_copy_present(coords):
                skip("dataset_copy_missing"); continue
        else:  # failed/cancelled (only with --include-failed)
            if args.scene and (coords is None or coords["scene_id"] != args.scene):
                skip("other_scene"); continue

        # Eligible.
        counts["eligible"] += 1
        if args.size:
            bytes_eligible += _dir_size_bytes(job_dir)
        if len(eligible_samples) < 8:
            eligible_samples.append(job_dir.name)

        if apply:
            dest = archive_root / job_dir.name
            try:
                if args.delete:
                    shutil.rmtree(job_dir)
                else:
                    archive_root.mkdir(parents=True, exist_ok=True)
                    if dest.exists():
                        skip("archive_dest_exists"); counts["eligible"] -= 1; continue
                    shutil.move(str(job_dir), str(dest))
                counts["archived"] += 1
            except Exception as exc:  # noqa: BLE001
                print(f"[archive]   FAIL {job_dir.name}: {exc}", file=sys.stderr)
                skip("move_error"); counts["eligible"] -= 1
                continue
            if args.limit and counts["archived"] >= args.limit:
                print(f"[archive] reached --limit {args.limit}", flush=True)
                break
        else:
            if args.limit and counts["eligible"] >= args.limit:
                break

    dt = time.time() - t0
    print("\n[archive] ===== summary =====")
    print(f"  scanned : {counts['scanned']}  ({dt:.1f}s)"
          + ("" if reached_end else "  [stopped early at --max-scan; re-run to continue]"))
    print(f"  eligible: {counts['eligible']}", end="")
    if args.size:
        print(f"   (~{bytes_eligible / 1e9:.2f} GB)")
    else:
        print()
    if apply:
        verb = "deleted" if args.delete else "moved"
        print(f"  {verb} : {counts['archived']} -> {archive_root if not args.delete else '(removed)'}")
    else:
        print(f"  DRY-RUN: nothing moved. Re-run with --apply to move {counts['eligible']} job(s).")
    if eligible_samples:
        print("  sample eligible:")
        for s in eligible_samples:
            print(f"    - {s}")
    if skipped:
        print("  skipped (left in place):")
        for reason, n in sorted(skipped.items(), key=lambda kv: -kv[1]):
            print(f"    {reason:28} {n}")


if __name__ == "__main__":
    main()
