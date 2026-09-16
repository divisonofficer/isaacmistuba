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
import subprocess
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


def device_residents() -> dict[str, list[tuple[int, int]]]:
    """GPU uuid -> [(pid, MiB)] from nvidia-smi, for devices held from anywhere.

    `bound_processes` reads /proc and therefore sees only this namespace. A
    device held by a process in another container shows nothing there, so a
    device with 22 GB resident reads as free -- which is exactly what GPU 3
    looked like from here while it was in use. The pid that query reports is
    useless for attribution, but the existence of the row is not, and the
    existence is the part that decides whether a device is free.

    Returns an empty map, not a clean bill of health, if nvidia-smi is missing:
    the caller must tell "nothing is running" apart from "nothing was asked".
    """
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,used_memory",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    residents: dict[str, list[tuple[int, int]]] = {}
    for line in output.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != 3:
            continue
        residents.setdefault(fields[0], []).append((int(fields[1]), int(fields[2])))
    return residents


def device_uuids() -> dict[int, str]:
    try:
        output = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=30, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    pairs = {}
    for line in output.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) == 2:
            pairs[int(fields[0])] = fields[1]
    return pairs


def occupancy(gpus: list[int]) -> dict[int, str]:
    """Why each of these devices is not free, for the ones that are not.

    Both views, because each is blind where the other sees: /proc attributes a
    device to a local job that is mid-CPU-phase and showing no utilisation,
    nvidia-smi catches a holder this namespace cannot see at all.
    """
    uuids = device_uuids()
    residents = device_residents()
    busy = {}
    for gpu in gpus:
        local = bound_processes(gpu)
        if local:
            busy[gpu] = f"local pids {local} name it in their own environment"
            continue
        uuid = uuids.get(gpu)
        if uuid is None:
            busy[gpu] = "nvidia-smi did not report this device; cannot say it is free"
            continue
        here = residents.get(uuid) or []
        if here:
            detail = ", ".join(f"pid {pid} holding {mib} MiB" for pid, mib in here)
            busy[gpu] = f"{detail} (not visible in this namespace)"
    return busy


def update(lock: Path, holder: str, gpus: list[int] | None, reason: str,
           reclaim: str | None = None, evidence: str = "") -> dict:
    """Read, mutate one key, write, read back."""
    document = json.loads(lock.read_text(encoding="utf-8")) if lock.is_file() else {}
    holders = dict(document.get("all_holders") or {})

    taken = {index: name for name, indices in holders.items()
             for index in indices if name != holder}
    collisions = {index: taken[index] for index in (gpus or []) if index in taken}

    if reclaim and collisions:
        # Taking over an abandoned row, which is a different act from taking a
        # device. Every guard below is about not doing it to a holder who is
        # merely quiet: a session that ended leaves a row behind, and a session
        # that is thinking leaves the same row behind.
        wrong_owner = {index: name for index, name in collisions.items() if name != reclaim}
        if wrong_owner:
            raise SystemExit(f"refusing: {wrong_owner} belong to a holder other than "
                             f"{reclaim!r}. Reclaim names one row and takes only that one.")
        if not evidence:
            raise SystemExit("refusing: --reclaim needs --evidence saying how you know that "
                             "holder is gone. It is recorded, not verified; a reclaim nobody "
                             "can audit later is a hand-edit with extra steps.")
        busy = occupancy(sorted(collisions))
        if busy:
            raise SystemExit("refusing: the row may be stale but the devices are not free: "
                             + "; ".join(f"gpu {gpu}: {why}" for gpu, why in sorted(busy.items())))
        holders[reclaim] = [index for index in holders.get(reclaim, [])
                            if index not in collisions]
        if not holders[reclaim]:
            holders.pop(reclaim, None)
        history = list(document.get("reclaimed") or [])
        history.append({"from": reclaim, "by": holder, "gpu_indices": sorted(collisions),
                        "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "evidence": evidence})
        document["reclaimed"] = history[-20:]
        collisions = {}

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
    parser.add_argument("--reclaim", metavar="HOLDER",
                        help="take these devices out of HOLDER's row: for a session that "
                             "ended and left its claim behind. Refused unless the devices "
                             "are idle in both views, and never a substitute for asking a "
                             "holder who is still there.")
    parser.add_argument("--evidence", default="",
                        help="how you know that holder is gone; recorded with the reclaim")
    args = parser.parse_args()

    if args.check:
        document = json.loads(args.lock.read_text(encoding="utf-8")) if args.lock.is_file() else {}
        holders = document.get("all_holders") or {}
        claimed = {index: name for name, indices in holders.items() for index in indices}
        busy = occupancy(list(range(8)))
        for gpu in range(8):
            state = busy.get(gpu, "idle")
            print(f"  gpu {gpu}: claimed by {claimed.get(gpu, '-'):>16s}   {state}")
        return 0

    if not args.holder:
        parser.error("--holder is required when writing")
    gpus = [int(v) for v in args.gpus.split(",") if v.strip()]
    landed = update(args.lock, args.holder, gpus, args.reason or "unstated",
                    reclaim=args.reclaim, evidence=args.evidence)
    print(json.dumps({"all_holders": landed["all_holders"],
                      "written_at": landed["written_at"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
