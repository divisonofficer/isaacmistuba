#!/usr/bin/env python3
"""The vetted target list for the ABO text corpus, and the QA that trims it.

A target earns its place by surviving two filters and a person. The census says
its texture carries words; the visibility screen says a render of it reads those
words back; and this file is where the third judgement lives -- the one that
cannot be automated, because "the render technically reads it but I don't want
it in the corpus" is a decision about the dataset, not a measurement of it.

Exclusions are kept with a reason and a timestamp, never deleted, so a target
that comes back later shows why it left. The corpus builder reads `active()`.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT = REPO / "configs" / "abo_text_targets.json"
SCHEMA = "robomituba.abo_text_targets.v1"


def load(path: Path) -> dict:
    if not path.is_file():
        return {"schema": SCHEMA, "targets": {}, "excluded": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise SystemExit(f"{path}: unexpected schema {data.get('schema')!r}")
    return data


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)          # atomic: a half-written target list is worse than none


def active(path: Path = DEFAULT) -> list[dict]:
    """Targets the corpus should shoot: screened in, not excluded by a person."""
    data = load(path)
    return [row for tid, row in sorted(data["targets"].items())
            if tid not in data["excluded"]]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=DEFAULT)
    ap.add_argument("--add-passes", type=Path,
                    help="screen_pass.json from the visibility screen; adds or updates targets")
    ap.add_argument("--exclude", nargs="+", metavar="ID", help="ABO ids to drop from the corpus")
    ap.add_argument("--reason", default="qa", help="why, recorded beside the exclusion")
    ap.add_argument("--restore", nargs="+", metavar="ID", help="undo an exclusion")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()

    if args.self_check:
        _self_check()
        return 0

    data = load(args.file)
    changed = False

    if args.add_passes:
        rows = json.loads(args.add_passes.read_text(encoding="utf-8"))
        for row in rows:
            tid = row["id"]
            data["targets"][tid] = {k: row[k] for k in
                                    ("id", "text", "text_h_m", "distance_m", "best_text", "cer")
                                    if k in row}
        print(f"[targets] {len(rows)} screened targets merged; {len(data['targets'])} total")
        changed = True

    if args.exclude:
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for tid in args.exclude:
            # An id that is not a target is almost always a typo, and silently
            # accepting it means the exclusion the person meant never happens.
            if tid not in data["targets"]:
                raise SystemExit(f"{tid} is not a screened target; nothing to exclude")
            data["excluded"][tid] = {"reason": args.reason, "at": at}
            print(f"[targets] excluded {tid}: {args.reason}")
        changed = True

    if args.restore:
        for tid in args.restore:
            if data["excluded"].pop(tid, None) is None:
                print(f"[targets] {tid} was not excluded")
            else:
                print(f"[targets] restored {tid}")
        changed = True

    if changed:
        save(args.file, data)

    if args.list or not changed:
        rows = active(args.file)
        print(f"[targets] {len(rows)} active, {len(data['excluded'])} excluded")
        for row in rows:
            print(f"  {row['id']} '{str(row.get('text'))[:22]}' "
                  f"{(row.get('text_h_m') or 0)*100:.2f}cm d={row.get('distance_m')}")
        for tid, why in sorted(data["excluded"].items()):
            print(f"  -- {tid} excluded: {why['reason']} ({why['at']})")
    return 0


def _self_check() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "t.json"
        passes = Path(tmp) / "p.json"
        passes.write_text(json.dumps([{"id": "A", "text": "x", "text_h_m": 0.01},
                                      {"id": "B", "text": "y", "text_h_m": 0.02}]))
        data = load(f)
        assert data["targets"] == {}
        rows = json.loads(passes.read_text())
        data["targets"] = {r["id"]: r for r in rows}
        data["excluded"] = {"B": {"reason": "qa", "at": "now"}}
        save(f, data)
        got = active(f)
        assert [r["id"] for r in got] == ["A"], got
        # an exclusion survives a re-merge of the same screen output
        data = load(f)
        data["targets"]["B"] = {"id": "B", "text": "y"}
        save(f, data)
        assert [r["id"] for r in active(f)] == ["A"], "re-adding must not un-exclude"
    print("self-check ok")


if __name__ == "__main__":
    raise SystemExit(main())
