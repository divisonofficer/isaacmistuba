"""audit.py — Phase 0 of the hpBRDF compression pipeline.

Reads each .hpbrdf file's TensorFile header without loading the multi-GB
Mueller cube, extracts the small metadata fields (wavelengths + angular
grids), and writes per-material JSON to `out/hpbrdf_compressed/`.

(File is named `audit` rather than `inspect` because Python's stdlib has
a top-level `inspect` module that `dataclasses` imports — naming this
file `inspect.py` and running it directly puts the script's directory
on `sys.path[0]` and shadows the stdlib import, which makes
`from dataclasses import dataclass` fail with a circular-import error.)

Pure-stdlib + numpy. Does NOT require Mitsuba — the inspector runs on
machines that don't have a CUDA build (e.g. Windows asset-validation
boxes), which is the same property `apps/validate_material_previews.py`
relies on.

Usage
    python tools/hpbrdf/audit.py
    python tools/hpbrdf/audit.py --material aluminum
    python tools/hpbrdf/audit.py --json | jq '.results[].material_id'

Exit codes
    0   all materials inspected successfully
    1   at least one material's header was malformed or unreadable
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Allow running as a script from repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "tools"))

from hpbrdf._tensor_file import TensorFile  # noqa: E402

# Reuse the canonical catalog so material_id / display_name / native_file
# stay in lockstep with what the daemon serves.
sys.path.insert(0, str(_REPO_ROOT / "modules" / "robomituba_bridge" / "src"))
sys.path.insert(0, str(_REPO_ROOT / "modules" / "mitsuba_converter" / "src"))
from mitsuba_converter.material_library import _HPBRDF_2025_MATERIALS  # type: ignore[import-not-found]  # noqa: E402

OUT_DIR = _REPO_ROOT / "out" / "hpbrdf_compressed"
SCHEMA_VERSION = "raw_meta_v1"


@dataclass
class InspectionError:
    material_id: str
    error: str


def _content_signature(path: Path) -> str:
    """Cheap fingerprint: SHA1 of head + tail 4 KB plus total size.

    Mirrors `_content_signature` in sphere_preview.py — full SHA1 of a
    13 GB file is ~30s; the head/tail/size combination is enough to detect
    any practical edit.
    """
    size = path.stat().st_size
    with path.open("rb") as f:
        head = f.read(4096)
        if size > 8192:
            f.seek(-4096, 2)
            tail = f.read(4096)
        else:
            tail = b""
    return f"{size:x}_{hashlib.sha1(head + tail).hexdigest()[:16]}"


def inspect_one(material_id: str, display_name: str, native_file: str) -> dict[str, Any]:
    """Open one .hpbrdf file, parse its header + small metadata fields,
    and return a JSON-serialisable dict."""
    path = _REPO_ROOT / native_file
    tf = TensorFile(path)

    # Map the patched-plugin field-name conventions onto a stable schema.
    # Real hpBRDF files have:
    #   M       float32 (phi_d, theta_d, theta_h, wavelengths, 4, 4)
    #   phi_d   float32 (1, n_phi_d)
    #   theta_d float32 (1, n_theta_d)
    #   theta_h float32 (1, n_theta_h)
    #   wvls    uint16  (n_wavelengths,)
    M = tf.fields["M"]
    if len(M.shape) != 6 or M.shape[-2:] != (4, 4):
        raise ValueError(
            f"unexpected M shape {M.shape}; expected (phi_d, theta_d, theta_h, n_wavelengths, 4, 4)"
        )
    n_phi_d, n_theta_d, n_theta_h, n_wavelengths, _, _ = M.shape

    # Read the small fields (KB-scale, safe to load).
    wvls = tf.read_field("wvls")
    theta_h = tf.read_field("theta_h")
    theta_d = tf.read_field("theta_d")
    phi_d = tf.read_field("phi_d")

    # The .pbsdf/.hpbrdf format stores wavelengths as uint16 nanometres.
    wavelengths_nm = [int(v) for v in wvls.tolist()]

    angular_total = n_phi_d * n_theta_d * n_theta_h
    spectral_polarimetric_dim = n_wavelengths * 16
    payload_bytes_full = angular_total * spectral_polarimetric_dim * 4

    return {
        "schema": SCHEMA_VERSION,
        "material_id": material_id,
        "display_name": display_name,
        "native_file": native_file,
        "file_size_bytes": tf.file_size,
        "tensor_file_version": list(tf.version),
        "n_wavelengths": n_wavelengths,
        "wavelengths_nm": wavelengths_nm,
        "wavelengths_nm_range": [
            min(wavelengths_nm), max(wavelengths_nm)
        ] if wavelengths_nm else None,
        "angular_shape": {
            "phi_d": n_phi_d,
            "theta_d": n_theta_d,
            "theta_h": n_theta_h,
        },
        "angular_total_bins": angular_total,
        "angular_grid_summary": {
            "phi_d": {"min": float(phi_d.min()), "max": float(phi_d.max())},
            "theta_d": {"min": float(theta_d.min()), "max": float(theta_d.max())},
            "theta_h": {"min": float(theta_h.min()), "max": float(theta_h.max())},
        },
        "mueller_layout": "row_major_4x4",
        "mueller_components": 16,
        "spectral_polarimetric_feature_dim": spectral_polarimetric_dim,
        "M_dtype": M.dtype_name,
        "M_shape": list(M.shape),
        "M_payload_bytes": payload_bytes_full,
        "content_signature": _content_signature(path),
        "inspected_at_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def write_meta(meta: dict[str, Any]) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{meta['material_id']}.raw_meta.json"
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--material",
        default=None,
        help="Inspect only this material_id (default: all 14).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the combined results to stdout as JSON instead of a human report.",
    )
    args = parser.parse_args()

    targets: list[tuple[str, str, str]] = list(_HPBRDF_2025_MATERIALS)
    if args.material:
        targets = [t for t in targets if t[0] == args.material]
        if not targets:
            print(f"unknown material_id: {args.material}", file=sys.stderr)
            return 1

    results: list[dict[str, Any]] = []
    errors: list[InspectionError] = []
    for material_id, display_name, native_file in targets:
        path = _REPO_ROOT / native_file
        if not path.exists():
            errors.append(InspectionError(material_id, f"file not found: {native_file}"))
            continue
        try:
            meta = inspect_one(material_id, display_name, native_file)
        except Exception as exc:
            errors.append(InspectionError(material_id, f"{type(exc).__name__}: {exc}"))
            continue
        write_meta(meta)
        results.append(meta)

    if args.json:
        print(json.dumps(
            {"results": results, "errors": [asdict(e) for e in errors]},
            indent=2, ensure_ascii=False,
        ))
    else:
        print(f"hpBRDF inspection — {len(results)} OK, {len(errors)} errors")
        print(f"out dir: {OUT_DIR.relative_to(_REPO_ROOT)}\n")
        for r in results:
            wnm = r["wavelengths_nm_range"]
            ash = r["angular_shape"]
            print(
                f"  {r['material_id']:<22} "
                f"{r['file_size_bytes'] / 1e9:>5.2f} GB  "
                f"M{tuple(r['M_shape'])} "
                f"λ={r['n_wavelengths']}@[{wnm[0]}-{wnm[1]}nm] "
                f"angular={ash['phi_d']}×{ash['theta_d']}×{ash['theta_h']} "
                f"sig={r['content_signature']}"
            )
        for e in errors:
            print(f"  [ERROR] {e.material_id:<22} {e.error}")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
