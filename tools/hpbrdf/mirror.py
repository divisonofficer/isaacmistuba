"""mirror.py — Copy a wavelength subset of the channel-split hpBRDF
dataset from bean (CIFS) into the project-local
`data/hpbrdf_2025/channels/{material_id}/` tree.

Default mode `rgbnir` mirrors only the 4 RGB+NIR bands — about 11 GB
total — which is enough to render the project's default preview tier
without any bean dependency. Use `visible` (10 bands, ~43 GB) or
`hyperspectral` (all 68 bands, ~170 GB) when you specifically need
better colour fidelity or full spectral analysis.

Idempotent — uses `rsync --update` so re-running skips files that are
already up to date. CIFS-to-CIFS rsync isn't blazing but it gets us
restartability + per-file progress for a multi-GB transfer.

Usage
    python tools/hpbrdf/mirror.py
    python tools/hpbrdf/mirror.py --mode visible
    python tools/hpbrdf/mirror.py --mode hyperspectral
    python tools/hpbrdf/mirror.py --material aluminum
    python tools/hpbrdf/mirror.py --dry-run
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "tools"))

from hpbrdf._catalog import (  # noqa: E402
    BEAN_NAME_BY_MATERIAL_ID, BEAN_ROOT, LOCAL_CHANNELS_DIR, MODE_WAVELENGTHS,
)


CHANNEL_FILE_BYTES = 191_326_626  # constant across the dataset (verified)


def _format_size(n_bytes: int) -> str:
    if n_bytes < 1024:
        return f"{n_bytes} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n_bytes //= 1024
        if n_bytes < 1024:
            return f"{n_bytes} {unit}"
    return f"{n_bytes} PB"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--mode",
        choices=tuple(MODE_WAVELENGTHS.keys()),
        default="rgbnir",
        help="Wavelength subset to mirror (default: rgbnir = 4 bands, ~11 GB).",
    )
    parser.add_argument(
        "--material", default=None,
        help="Mirror only this catalog material_id.",
    )
    parser.add_argument(
        "--bean-root", type=Path, default=Path(BEAN_ROOT),
        help="Source root containing the per-material bean dirs.",
    )
    parser.add_argument(
        "--dest", type=Path, default=_REPO_ROOT / LOCAL_CHANNELS_DIR,
        help="Destination root. material_id subdirs are created underneath.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be copied without executing rsync.",
    )
    args = parser.parse_args()

    if not shutil.which("rsync"):
        print("rsync is required but was not found on PATH", file=sys.stderr)
        return 2

    targets: list[tuple[str, str]] = list(BEAN_NAME_BY_MATERIAL_ID.items())
    if args.material:
        targets = [t for t in targets if t[0] == args.material]
        if not targets:
            print(f"unknown material_id: {args.material}", file=sys.stderr)
            return 1

    wavelengths = MODE_WAVELENGTHS[args.mode]
    total_files = len(targets) * len(wavelengths)
    total_bytes_estimate = total_files * CHANNEL_FILE_BYTES
    print(
        f"hpBRDF mirror — mode={args.mode}  "
        f"materials={len(targets)}  channels/material={len(wavelengths)}  "
        f"total_files={total_files}  est_size={_format_size(total_bytes_estimate)}"
    )
    print(f"  src: {args.bean_root}")
    print(f"  dst: {args.dest.relative_to(_REPO_ROOT) if args.dest.is_relative_to(_REPO_ROOT) else args.dest}")
    print()

    failed: list[str] = []
    for material_id, bean_dir in targets:
        src_dir = args.bean_root / bean_dir
        dst_dir = args.dest / material_id
        if not src_dir.exists():
            print(f"  ✕ {material_id:<22} src dir missing: {src_dir}")
            failed.append(material_id)
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)

        # Build an `--include` filter that keeps only the wavelengths for
        # this mode; rsync skips everything else. Order matters: includes
        # before the wildcard exclude.
        # `-r` is required for include/exclude filters to actually walk
        # the source directory's children — without it rsync skips the
        # whole tree with "skipping directory ." and the filter rules
        # never get evaluated.
        rsync_args = [
            "rsync", "-r", "--update", "--times", "--itemize-changes",
            "--no-perms", "--no-owner", "--no-group", "--chmod=ugo=rwX",
        ]
        if args.dry_run:
            rsync_args.append("--dry-run")
        for w in wavelengths:
            rsync_args += ["--include", f"{w}.pbrdf"]
        rsync_args += ["--exclude", "*"]
        # Trailing slash on src so rsync syncs CONTENTS (not src dir itself).
        rsync_args += [f"{src_dir}/", f"{dst_dir}/"]

        print(f"  → {material_id:<22} ", end="", flush=True)
        try:
            result = subprocess.run(
                rsync_args, check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:
            print(f"FAILED (exit {exc.returncode})")
            print(f"    stderr: {exc.stderr.strip()[:200]}")
            failed.append(material_id)
            continue
        # itemize-changes prints one line per file actually transferred.
        # Empty stdout means everything was already up to date.
        transferred = [l for l in result.stdout.splitlines() if l and not l.startswith("sending")]
        print(f"{len(transferred):>2} new/updated")

    if failed:
        print(f"\n{len(failed)} materials failed: {', '.join(failed)}")
        return 1
    print("\nall materials mirrored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
