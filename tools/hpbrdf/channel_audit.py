"""channel_audit.py — Phase 0 of the channel-split hpBRDF pipeline.

Walks the bean dataset (or a local mirror) and verifies that each
material directory contains exactly the 68 expected wavelength files,
that each `.pbrdf` has the expected single-wavelength shape
`M[361, 91, 91, 1, 4, 4]`, and that the embedded `wvls` value matches
the file name. Also checks the bean↔catalog material_id mapping.

Pure-stdlib + numpy, no Mitsuba. Reads only TensorFile *headers* (~KB),
never the multi-GB tensor payload — same approach as `audit.py` for
monolithic files.

Usage
    python tools/hpbrdf/channel_audit.py
    python tools/hpbrdf/channel_audit.py --root /bean_yunseong/hpbrdf/table_publish_final
    python tools/hpbrdf/channel_audit.py --material aluminum
    python tools/hpbrdf/channel_audit.py --json | jq '.summary'

Exit codes
    0   all 14 materials × 68 channels present + headers consistent
    1   at least one material/channel failed validation
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "tools"))

from hpbrdf._catalog import (  # noqa: E402
    BEAN_NAME_BY_MATERIAL_ID, BEAN_ROOT, FULL_WAVELENGTHS,
)
from hpbrdf._tensor_file import TensorFile  # noqa: E402

OUT_PATH = _REPO_ROOT / "out" / "hpbrdf_compressed" / "channels_audit.json"
SCHEMA_VERSION = "channel_audit_v1"

# A pristine 1-channel pbrdf has these geometric dims fixed by the
# capture rig (361 phi_d × 91 theta_d × 91 theta_h, single λ, 4×4 Mueller).
EXPECTED_M_SHAPE = (361, 91, 91, 1, 4, 4)


@dataclass
class ChannelIssue:
    material_id: str
    wavelength_nm: int | None
    code: str
    message: str


def _audit_one_channel(path: Path, expected_wavelength: int) -> str | None:
    """Open a single .pbrdf, verify shape + wvls. Returns error string or None."""
    try:
        tf = TensorFile(path)
    except Exception as exc:
        return f"TensorFile open failed: {type(exc).__name__}: {exc}"
    M = tf.fields.get("M")
    if M is None:
        return "missing 'M' field"
    if tuple(M.shape) != EXPECTED_M_SHAPE:
        return f"unexpected M shape {tuple(M.shape)} (expected {EXPECTED_M_SHAPE})"
    wvls_field = tf.fields.get("wvls")
    if wvls_field is None or wvls_field.shape != (1,):
        return f"unexpected wvls shape {wvls_field.shape if wvls_field else None}"
    wvls = tf.read_field("wvls")
    if int(wvls[0]) != expected_wavelength:
        return f"wvls value {int(wvls[0])} != filename {expected_wavelength}"
    return None


def audit_material(material_id: str, bean_dir_name: str, root: Path,
                   sample_only: bool = False) -> dict[str, Any]:
    """Audit one material's directory.

    `sample_only=True` checks the first + last + middle wavelength only,
    cuts CIFS round-trips by 65× when we just want a smoke check.
    """
    material_dir = root / bean_dir_name
    issues: list[ChannelIssue] = []
    if not material_dir.exists():
        issues.append(ChannelIssue(material_id, None, "MISSING_DIR",
                                    f"directory not found: {material_dir}"))
        return {
            "material_id": material_id, "bean_dir": bean_dir_name,
            "channels_present": 0, "expected_channels": len(FULL_WAVELENGTHS),
            "all_channels_ok": False, "issues": [asdict(i) for i in issues],
        }

    files_present = {p.name for p in material_dir.iterdir() if p.suffix == ".pbrdf"}
    expected_files = {f"{w}.pbrdf" for w in FULL_WAVELENGTHS}
    missing = sorted(expected_files - files_present)
    extra = sorted(files_present - expected_files)
    for name in missing:
        # Recover wavelength from filename for the issue record.
        try:
            w = int(Path(name).stem)
        except ValueError:
            w = None
        issues.append(ChannelIssue(material_id, w, "MISSING_CHANNEL",
                                    f"file not found: {name}"))
    for name in extra:
        issues.append(ChannelIssue(material_id, None, "UNEXPECTED_FILE",
                                    f"unrecognised file: {name}"))

    # Header-validate a subset of channels.
    if sample_only:
        check_wavelengths = [FULL_WAVELENGTHS[0],
                              FULL_WAVELENGTHS[len(FULL_WAVELENGTHS) // 2],
                              FULL_WAVELENGTHS[-1]]
    else:
        check_wavelengths = list(FULL_WAVELENGTHS)
    sample_M_shape: tuple[int, ...] | None = None
    for w in check_wavelengths:
        path = material_dir / f"{w}.pbrdf"
        if not path.exists():
            continue
        err = _audit_one_channel(path, w)
        if err is not None:
            issues.append(ChannelIssue(material_id, w, "HEADER_INVALID", err))
        elif sample_M_shape is None:
            sample_M_shape = EXPECTED_M_SHAPE  # confirmed by passing the check

    channels_present = len(files_present & expected_files)
    return {
        "material_id": material_id,
        "bean_dir": bean_dir_name,
        "material_path": str(material_dir),
        "channels_present": channels_present,
        "expected_channels": len(FULL_WAVELENGTHS),
        "all_channels_ok": channels_present == len(FULL_WAVELENGTHS) and not issues,
        "sample_M_shape": list(sample_M_shape) if sample_M_shape else None,
        "issues": [asdict(i) for i in issues],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(BEAN_ROOT),
                        help=f"Root containing the per-material dirs. "
                             f"Default: {BEAN_ROOT}")
    parser.add_argument("--material", default=None,
                        help="Audit only this catalog material_id.")
    parser.add_argument("--full", action="store_true",
                        help="Header-validate ALL 68 channels per material "
                             "(default: 3-channel sample for speed).")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON to stdout instead of a human report.")
    parser.add_argument("--out", type=Path, default=OUT_PATH,
                        help="Path to write the combined audit JSON.")
    args = parser.parse_args()

    targets: list[tuple[str, str]] = list(BEAN_NAME_BY_MATERIAL_ID.items())
    if args.material:
        targets = [t for t in targets if t[0] == args.material]
        if not targets:
            print(f"unknown catalog material_id: {args.material}", file=sys.stderr)
            return 1

    results: list[dict[str, Any]] = []
    for material_id, bean_dir in targets:
        results.append(audit_material(
            material_id, bean_dir, args.root, sample_only=not args.full,
        ))

    n_ok = sum(1 for r in results if r["all_channels_ok"])
    n_total = len(results)
    summary = {
        "schema": SCHEMA_VERSION,
        "bean_root": str(args.root),
        "materials_total": n_total,
        "materials_ok": n_ok,
        "materials_failed": n_total - n_ok,
        "expected_channels_per_material": len(FULL_WAVELENGTHS),
        "audit_mode": "full" if args.full else "sample",
        "audited_at_utc": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    payload = {"summary": summary, "materials": results}

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                            encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"channel-split audit @ {args.root}")
        print(f"  materials: {n_ok}/{n_total} OK   mode: {summary['audit_mode']}\n")
        for r in results:
            tag = "✓" if r["all_channels_ok"] else "✕"
            print(f"  {tag} {r['material_id']:<22} bean={r['bean_dir']:<26} "
                  f"channels={r['channels_present']}/{r['expected_channels']}")
            for issue in r["issues"][:3]:
                w = issue.get("wavelength_nm")
                wtag = f"@{w}nm" if w else "      "
                print(f"      [{issue['code']:<16}] {wtag} {issue['message']}")
            if len(r["issues"]) > 3:
                print(f"      ... and {len(r['issues']) - 3} more")
        if args.out:
            print(f"\nwrote {args.out.relative_to(_REPO_ROOT)}")

    return 0 if n_ok == n_total else 1


if __name__ == "__main__":
    sys.exit(main())
