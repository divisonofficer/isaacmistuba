# Quarantine to /friday (user decision 2026-10-07)

Goal: get /bean under the user's 3 TB quota WITHOUT deleting anything. Data that no current
training run and no live or queued render reads is MOVED to the friday NAS, not deleted.

## Where
- Mount: `/friday` = `//141.223.92.74/log/jinnyeong` (CIFS). The user calls it `/friday/jinnyeong`;
  inside this container that is `/friday`.
- Destination root: `/friday/quarantine/`. Mirror the original absolute path under it, so restore
  is a plain copy back:
  `/bean/ir_dataset/abo_cornell_env_v1/abo_env_0005/x.blend`
  → `/friday/quarantine/bean/ir_dataset/abo_cornell_env_v1/abo_env_0005/x.blend`
- Volume had 3.3 TB free on 2026-10-07 (90% used). Check `df -h /friday` before each batch;
  stop if free space would fall under 500 GB.

## What qualifies (owner decides, one item at a time)
- NOT read by the current training manifest (corpus v10), the running training config, or the
  loader cache rows that v10 references (ask IR_PIPELINE when unsure).
- NOT an input to any live or queued render queue (HSSD v5/hover/walk/lighting, ABO text_v1,
  Infinigen hover/walk). Blends of scenes that will not be re-rendered qualify.
- NOT an eval take (ABO env_v2 0012/0024/0031 stay put entirely).
- NOT a sole source that a live pipeline reads (Infinigen KEEP_SOLE_SOURCE.txt blends stay).
- Typical: .blend / assets / stage of frozen scenes, unpromoted staging, old corpora outside v10,
  superseded trees, old logs, checkpoint.pt of finished runs (weights_ep* stay).

## How (per batch)
1. `df -h /friday /bean` before.
2. Copy: `rsync -rt --partial <src> /friday/quarantine/<mirror>/` (CIFS: no owners, no symlinks;
   `-a` fails on chown. If the source holds symlinks, list them and stop.)
3. Verify EVERY file: same relative path and byte size on both sides; sha256 of every file
   ≥ 100 MB (all blends) and a 1-in-20 sample of the rest. Any mismatch: stop, leave the source.
4. Check nothing holds the source open (`/proc/*/fd`), then delete the source.
5. Leave `QUARANTINED_TO_FRIDAY.txt` in the source's parent dir: what moved, where, when, who.
6. Append one JSON line per moved top-level path to `/friday/quarantine/MANIFEST.jsonl`:
   `{"src","dst","bytes","files","sha256_checked","owner","reason","date","restore":"rsync -rt <dst> <src_parent>/"}`
7. `df -h /bean` after; report bytes moved.

Rules: one mover per owner at a time, `nice -n 10 ionice -c3`, first batch small (≤ 50 GB),
CIFS is a soft mount and can return I/O errors under load, so never delete on a partial copy.
