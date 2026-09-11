#!/usr/bin/env python3
"""Claim or release this session's GPUs in the shared pool lock.

Written because hand-editing that file went wrong twice in one afternoon, in
two ways worth naming.

**Rebuilding the map drops rows.** A write that constructs `all_holders` from a
copy read earlier silently discards every row added between the read and the
write, and the result looks entirely correct -- there is no gap, no conflict,
just a live holder that is no longer mentioned. One of my writes dropped a
peer's live claim on two GPUs that way. So this reads immediately before
writing and mutates exactly one key: the caller's own.

**A hand-typed timestamp is not a timestamp.** I set `written_at` to a round
value I typed, which landed twelve minutes ahead of the file's mtime. Another
session reconstructed the order of events from that field and got it wrong by
those twelve minutes, then had to retract the conclusion it drew. A field that
says when something happened, and does not, is worse than no field: it is
believed. The stamp here comes from the same clock read that performs the
write, with microseconds, and the file is read back afterwards to confirm what
landed.

Neither problem is exotic. Both are the same shape as everything else this week
-- a recorded fact diverging from the deciding fact -- and both were introduced
by me doing by hand what a function should do.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

DEFAULT_LOCK = Path("/bean/ir_dataset_work/gpu_pool.lock.json")


def bound_processes(gpu: int) -> list[int]:
    """Live pids whose own environment names this GPU.

    Not utilisation and not `nvidia-smi --query-compute-apps`: a job in a CPU
    phase holds its device while showing neither, and the host pids that query
    reports are in a different namespace from the ones visible here, so a
    pid-to-owner comparison finds no owner for anything and reads exactly like
    an idle machine.
    """
    needle = f"CUDA_VISIBLE_DEVICES={gpu}"
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if needle in (entry / "environ").read_bytes().decode("utf-8", "replace").split("\0"):
                found.append(int(entry.name))
        except OSError:
            continue
    return sorted(found)


def update(lock: Path, holder: str, gpus: list[int] | None, reason: str) -> dict:
    """Read, mutate one key, write, read back."""
    document = json.loads(lock.read_text(encoding="utf-8")) if lock.is_file() else {}
    holders = dict(document.get("all_holders") or {})

    taken = {index: name for name, indices in holders.items()
             for index in indices if name != holder}
    collisions = {index: taken[index] for index in (gpus or []) if index in taken}
    if collisions:
        raise SystemExit(f"refusing: {collisions} already claimed by another holder. "
                         "Ask them; a row you did not write is not yours to overwrite.")

    if gpus:
        holders[holder] = sorted(gpus)
    else:
        holders.pop(holder, None)

    now = datetime.datetime.now(datetime.timezone.utc)
    document["all_holders"] = holders
    document["holder"] = holder
    document["gpu_indices"] = sorted(gpus or [])
    document["written_at"] = now.isoformat()
    document["reason"] = reason
    document.pop("unclaimed", None)   # an absence is not a claim and ages badly

    temporary = lock.with_suffix(".json.writing")
    temporary.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, lock)

    landed = json.loads(lock.read_text(encoding="utf-8"))
    if landed.get("all_holders") != holders:
        raise SystemExit("wrote the lock and read back something else; another session "
                         "wrote between the two. Re-run.")
    return landed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--holder", help="this session's name; required unless --check")
    parser.add_argument("--gpus", default="", help="comma-separated; empty releases the row")
    parser.add_argument("--reason", default="", help="what the devices are for")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--check", action="store_true",
                        help="report who is bound to each device and exit without writing")
    args = parser.parse_args()

    if args.check:
        document = json.loads(args.lock.read_text(encoding="utf-8")) if args.lock.is_file() else {}
        holders = document.get("all_holders") or {}
        claimed = {index: name for name, indices in holders.items() for index in indices}
        for gpu in range(8):
            pids = bound_processes(gpu)
            print(f"  gpu {gpu}: claimed by {claimed.get(gpu, '-'):>16s}   "
                  f"bound pids {pids or '-'}")
        return 0

    if not args.holder:
        parser.error("--holder is required when writing")
    gpus = [int(v) for v in args.gpus.split(",") if v.strip()]
    landed = update(args.lock, args.holder, gpus, args.reason or "unstated")
    print(json.dumps({"all_holders": landed["all_holders"],
                      "written_at": landed["written_at"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
