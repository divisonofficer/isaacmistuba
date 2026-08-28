# IR Dataset Viewer

Standalone viewer for `robomituba.ir_principled_dataset.v2`. It discovers
datasets below `/bean/ir_dataset` and `out/ir_dataset`, renders scientific
previews on demand, and never modifies source artifacts. The only write action
is the explicit, immutable `out -> /bean` publish workflow.

The app-local Python backend lives in `backend/`: `catalog.py` owns dataset
browsing/preview decoding and `controller.py` owns Control Center orchestration.
`mitsuba_converter` retains only shared IR contracts and the standalone
publisher, so the renderer package does not depend on this app.

## Development

```bash
cd /jarvis/project/robomituba/apps/ir_dataset_viewer
npm install
bash run_dev.sh
```

Open `http://<host>:5174`. The backend listens on port `8780`.
The dev server deliberately uses polling because the shared mount may exhaust
the Linux inotify quota; edits can take up to one second to refresh.
Render queues default to at most three GPUs per active dataset; set
`ROBOMITUBA_MAX_GPUS_PER_RENDER_PARENT=2` when preserving a two-GPU allocation
policy is required.

## Built frontend

```bash
cd apps/ir_dataset_viewer
npm run check
npm run build
python3 server.py --host 0.0.0.0 --port 8780
```

Open `http://<host>:8780/`. The Python backend serves the built SPA at `/`,
including SPA deep links, and serves API endpoints under `/api/*`.

## Publish without the UI

```bash
python3 apps/publish_ir_dataset.py \
  --dataset out/ir_dataset/<dataset-name> \
  --name <published-name>
```

Publication validates every indexed artifact, writes a SHA-256 inventory,
copies into `/bean/ir_dataset/.staging`, verifies every destination file, and
only then atomically exposes the final directory. A different fingerprint is
never allowed to overwrite an existing published name.

## Scene-scale inverse-rendering readiness labels

Published datasets stay immutable.  Dataset-level research-readiness labels
are fingerprint/source-hash-bound sidecars under
`/bean/ir_dataset_work/.catalog_quality_labels` and can be refreshed with:

```bash
python3 apps/label_ir_inverse_rendering_readiness.py
```

The v1 classifier marks a dataset `below_target` when the legacy selected-view
total-object median is below 10.  It never claims that a dataset is ready from
that proxy alone: specular object identity, raster coverage, and visible PBR
diversity remain explicitly `unverified` until a raster probe is available.
# Passive NIR migration

New controller jobs can request the paired observation contract and emit
`nir_active`, `nir_passive` (flash off), and the linear
`nir_active_minus_passive` EXR.  Existing completed datasets are migrated one
at a time without re-rendering RGB or GT:

```bash
python3 apps/backfill_ir_nir_passive.py \
  --dataset /bean/ir_dataset_work/<dataset> \
  --prepared-scene-dir /bean/ir_dataset_work/.pipeline/<job>/principled_stage2 \
  --gpu-index 0
```

The command keeps a lock and resumable state in
`<dataset>/.nir_passive_backfill/`; completed frame artifacts are never
overwritten. Use `--limit 1 --dry-run` to inspect the next frame before
claiming a GPU. The prepared blend must correspond to the dataset's scene and
the dataset must already contain `nir_active` frames.

For production queues, submit the migration as a controller GPU job so it
waits behind current render leases instead of competing with them:

```bash
curl -X POST http://127.0.0.1:8780/api/controller/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "source_mode": "nir_passive_backfill",
    "dataset_name": "nir_passive_backfill_<dataset>_v01",
    "backfill_dataset": "/bean/ir_dataset_work/<dataset>",
    "prepared_scene_dir": "/bean/ir_dataset_work/.pipeline/<job>/principled_stage2",
    "gpu_indices": [0,1,2,3,4,5,6,7],
    "priority": 80
  }'
```

The controller reserves one available GPU for this stage and runs the
backfill CLI only after the lease is acquired. Set `backfill_limit` to `1`
for a one-frame smoke test; omitting it processes the remaining frames of the
dataset and remains resumable.
