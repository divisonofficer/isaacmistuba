# Measured pBRDF datasets — deprecated 2026-08-05

`pbrdf_2020` and `hpbrdf_2025` were removed from local disk to reclaim ~203 GB.
They are **deprecated, not gone upstream**: the project renders with
full-analytic BSDFs, so nothing on the active render path needs them.

`configs/datasets/datasets.yaml` is the source of truth — both entries carry
`enabled: false` plus a `deprecated:` block with the restore recipe. This file
exists because `data/` is gitignored, so the in-tree `data/*/RESTORE.md` notes
do not survive a fresh clone.

## What was removed

| path | size | role |
|---|---:|---|
| `data/hpbrdf_2025/channels/{material}/{414..950}.pbrdf` | 10 GB | **canonical** — per-band slices the renderer reads |
| `data/hpbrdf_2025/raw/*.hpbrdf` (14 files) | 170 GB | legacy monolithic blobs; **not** needed to render |
| `data/pbrdf_2020/mitsuba/*.pbsdf` | 23 GB | KAIST pBRDF (Baek et al. 2020) |

## Restore

### hpbrdf_2025 (channel slices — the one you want)

```bash
python tools/hpbrdf/mirror.py                       # RGB+NIR tier, ~11 GB
python tools/hpbrdf/mirror.py --mode visible        # 10 bands, ~43 GB
python tools/hpbrdf/mirror.py --mode hyperspectral  # all 68 bands, ~170 GB
```

Idempotent rsync from `/bean_yunseong/hpbrdf/table_publish_final`, so a partial
transfer can be re-run. **The bean share must be mounted** — it was not
reachable when the data was deleted, so verify access before relying on this.

Monolithic `raw/` blobs, only for full-spectrum analysis:
<https://vclab.kaist.ac.kr/siggraphasia2025p3/>

Rendering also needs the KAIST plugin patch, unaffected by this deletion:
`third_party/hpbrdf_patch/` + `scripts/apply_hpbrdf_patch.sh`.

### pbrdf_2020

Download and unpack the Mitsuba-format `.pbsdf` files to
`data/pbrdf_2020/mitsuba/`: <https://vclab.kaist.ac.kr/siggraph2020/index.html>

No plugin patch required (`direct_mitsuba_support: true`).

After restoring either dataset, set its `enabled: true` in
`configs/datasets/datasets.yaml`.

## How code sees a deprecated dataset

`mitsuba_converter.material_library` reads the `deprecated:` block:

| helper | behaviour |
|---|---|
| `dataset_deprecation(root, id)` | the block, or `None` when live |
| `deprecation_message(root, id)` | one-line actionable message |
| `require_dataset(root, id)` | raises `FileNotFoundError` with the restore recipe |

Call `require_dataset` at the point of real consumption (loading a `.pbsdf` or
channel slice), not at import time — listing materials in the webui keeps
working and simply reports them as `not_downloaded`.
