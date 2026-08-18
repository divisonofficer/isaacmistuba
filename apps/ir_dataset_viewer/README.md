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
