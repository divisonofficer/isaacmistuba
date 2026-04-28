"""validate_material_previews.py — Audit baked curated preview PNGs.

Reliability gap closed: every time `_RIG_SPEC` changes in
`sphere_preview.py`, on-disk baked PNGs at `assets/material_previews/curated/`
become stale. The daemon flags `preview_status: stale` at runtime by
comparing each sidecar's `rig_hash` against the live rig — but there is no
commit-time / CI-time gate that catches "rig was bumped, bake was
forgotten" before it ships, so a developer who bumps `PREVIEW_PRESET_ID`
without re-baking can ship a release where every curated thumbnail in the
UI shows "프리뷰 오래됨" until the user manually invalidates each one.

This script is that gate. For every entry in the curated catalog it checks:

    - Baked PNG exists at the canonical path
    - Sidecar `.meta.json` exists alongside and parses as JSON
    - sidecar.preview_preset == sphere_preview.PREVIEW_PRESET_ID
    - sidecar.rig_hash       == sphere_preview.rig_hash()
    - PNG opens cleanly (PIL.Image.verify) — not truncated / corrupt
    - PNG mode is RGBA (sphere-only rig writes RGBA so transparent
      background can blend into the host UI surface — pre-v9 RGB bakes
      will render as opaque squares on the card and need re-baking)
    - PNG resolution matches sidecar.resolution

Emits a per-material report + summary counts. Pure-stdlib + PIL — does NOT
require Mitsuba to be installed, so the same script runs in CI on Linux
and on a Windows asset-validation box without GPU constraints.

Exit codes
    0   all materials pass
    1   at least one ERROR (use as a CI gate on PRs that touch the rig
        or asset PNGs)
    2   --strict and at least one WARNING

Usage
    python apps/validate_material_previews.py
    python apps/validate_material_previews.py --json | jq '.summary'
    python apps/validate_material_previews.py --strict
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Make the in-tree mitsuba_converter + robomituba_bridge packages
# importable without `pip install -e` so the script runs unchanged in CI /
# Windows asset-validation boxes. The validator only needs three names
# from the Mitsuba package (`PREVIEW_PRESET_ID`, `rig_hash()`, and the
# path helpers), but its `__init__.py` eagerly imports `mitsuba_builder`,
# which transitively requires `robomituba_bridge.material_mapping` —
# hence both paths are inserted up front.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "modules" / "robomituba_bridge" / "src"))
sys.path.insert(0, str(_REPO_ROOT / "modules" / "mitsuba_converter" / "src"))

from mitsuba_converter.bake_curated_previews import curated_meta_path  # type: ignore[import-not-found]  # noqa: E402
from mitsuba_converter.curated_library import (  # type: ignore[import-not-found]  # noqa: E402
    curated_preview_path,
    list_curated_materials,
)
from mitsuba_converter.sphere_preview import PREVIEW_PRESET_ID, rig_hash  # type: ignore[import-not-found]  # noqa: E402


SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass
class Issue:
    material_id: str
    severity: str
    code: str
    message: str


def _try_open_png(path: Path) -> tuple[str, tuple[int, int]] | str:
    """Verify PNG integrity + return (mode, (w, h)) or an error string."""
    try:
        from PIL import Image
    except ImportError:
        return "PIL/Pillow is required for PNG validation"
    try:
        # verify() walks the file's chunk structure but invalidates the
        # Image object — so we re-open afterwards to read mode/size.
        with Image.open(path) as im:
            im.verify()
        with Image.open(path) as im:
            return im.mode, im.size
    except Exception as exc:
        return f"PIL.open failed: {exc}"


def _parse_sidecar(path: Path) -> dict[str, Any] | str:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"JSON parse failed: {exc}"


def validate(repo_root: Path) -> tuple[list[Issue], int]:
    """Run all checks. Returns (issues, total_materials)."""
    issues: list[Issue] = []
    expected_preset = PREVIEW_PRESET_ID
    expected_hash = rig_hash()
    materials = list_curated_materials()

    for mat in materials:
        png = curated_preview_path(repo_root, mat.material_id)
        meta = curated_meta_path(repo_root, mat.material_id)

        if not png.exists():
            issues.append(Issue(
                mat.material_id, SEVERITY_ERROR, "MISSING_PNG",
                f"baked PNG not found: {png.relative_to(repo_root)}",
            ))
            continue

        # Sidecar may be missing on legacy bakes (pre-sidecar era). That's a
        # warning, not an error — but it means we can't verify preset/hash,
        # so re-bake is recommended.
        expected_resolution: list[int] | None = None
        if not meta.exists():
            issues.append(Issue(
                mat.material_id, SEVERITY_WARNING, "MISSING_META",
                f"sidecar absent (legacy bake?): {meta.relative_to(repo_root)}",
            ))
        else:
            payload = _parse_sidecar(meta)
            if isinstance(payload, str):
                issues.append(Issue(
                    mat.material_id, SEVERITY_ERROR, "META_MALFORMED",
                    f"{meta.name}: {payload}",
                ))
                continue
            if payload.get("preview_preset") != expected_preset:
                issues.append(Issue(
                    mat.material_id, SEVERITY_ERROR, "STALE_PRESET",
                    f"sidecar.preview_preset={payload.get('preview_preset')!r} "
                    f"!= current {expected_preset!r}",
                ))
            if payload.get("rig_hash") != expected_hash:
                issues.append(Issue(
                    mat.material_id, SEVERITY_ERROR, "STALE_HASH",
                    f"sidecar.rig_hash={payload.get('rig_hash')!r} "
                    f"!= current {expected_hash!r}",
                ))
            res = payload.get("resolution")
            if isinstance(res, list) and len(res) == 2 and all(isinstance(v, int) for v in res):
                expected_resolution = res

        result = _try_open_png(png)
        if isinstance(result, str):
            issues.append(Issue(
                mat.material_id, SEVERITY_ERROR, "CORRUPT",
                f"{png.name}: {result}",
            ))
            continue
        mode, (w, h) = result
        if mode != "RGBA":
            issues.append(Issue(
                mat.material_id, SEVERITY_WARNING, "WRONG_FORMAT",
                f"{png.name} mode={mode}, expected RGBA "
                f"(re-bake required after the sphere-only rig switch)",
            ))
        if expected_resolution is not None:
            ew, eh = expected_resolution
            if (w, h) != (ew, eh):
                issues.append(Issue(
                    mat.material_id, SEVERITY_WARNING, "WRONG_RESOLUTION",
                    f"{png.name} {w}x{h} != sidecar {ew}x{eh}",
                ))

    return issues, len(materials)


def _summary(issues: list[Issue], total_materials: int) -> dict[str, Any]:
    n_err = sum(1 for i in issues if i.severity == SEVERITY_ERROR)
    n_warn = sum(1 for i in issues if i.severity == SEVERITY_WARNING)
    erroring_ids = {i.material_id for i in issues if i.severity == SEVERITY_ERROR}
    return {
        "preset": PREVIEW_PRESET_ID,
        "rig_hash": rig_hash(),
        "total_materials": total_materials,
        "ok": total_materials - len(erroring_ids),
        "errors": n_err,
        "warnings": n_warn,
    }


def _print_human_report(issues: list[Issue], summary: dict[str, Any]) -> None:
    print(
        f"Curated preview audit — preset={summary['preset']} "
        f"rig={summary['rig_hash']}"
    )
    print(
        f"  total={summary['total_materials']}  ok={summary['ok']}  "
        f"errors={summary['errors']}  warnings={summary['warnings']}"
    )
    print()
    if not issues:
        print("✓ all baked previews match the current rig.")
        return
    for i in issues:
        tag = "ERROR" if i.severity == SEVERITY_ERROR else "WARN "
        print(f"  [{tag}] {i.material_id:<24} {i.code:<18} {i.message}")


def _default_repo_root() -> Path:
    return _REPO_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify baked curated preview PNGs match the current sphere "
            "preview rig. Exits non-zero if any are stale, corrupt, or "
            "missing — wire as a CI gate on PRs touching sphere_preview.py "
            "or assets/material_previews/curated/."
        )
    )
    parser.add_argument(
        "--repo-root", type=Path, default=_default_repo_root(),
        help="Repository root. Defaults to the parent of this script.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Machine-readable output for CI parsing.",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero on WARNING too (default: errors only).",
    )
    args = parser.parse_args()

    issues, total = validate(args.repo_root.resolve())
    summary = _summary(issues, total)

    if args.json:
        print(json.dumps(
            {"summary": summary, "issues": [asdict(i) for i in issues]},
            indent=2, ensure_ascii=False,
        ))
    else:
        _print_human_report(issues, summary)

    if summary["errors"] > 0:
        return 1
    if args.strict and summary["warnings"] > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
