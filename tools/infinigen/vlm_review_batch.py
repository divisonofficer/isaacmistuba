"""Run vlm_review.py for every room of one finished render round (called at the end of gt_round.sh, or by hand).

  python tools/infinigen/vlm_review_batch.py TAG ROUND [--rooms r1,r2] [--max-views 5] [--workers 3]
Reads /tmp/claude-0/objreal/rvs_<TAG>_<ROUND> (+ gt_<TAG>_<ROUND>), compares with the newest older round snapshot of the same tag, writes
out/vlm_review/<TAG>_<ROUND>/<room>.json and one line per room to stdout. A room view is a *_wide* png; close-ups are not reviewed.
"""
import argparse, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

O = Path("/tmp/claude-0/objreal"); REPO = Path("/jarvis/project/robomituba"); HERE = Path(__file__).parent


def prev_round(tag, rnd):
    n = int(rnd[1:]); older = sorted((int(m.group(1)) for p in O.glob(f"rvs_{tag}_r*") if (m := re.search(r"_r(\d+)$", p.name)) and int(m.group(1)) < n), reverse=True)
    return O / f"rvs_{tag}_r{older[0]}" if older else None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("tag"); ap.add_argument("round"); ap.add_argument("--rooms"); ap.add_argument("--max-views", default="5")
    ap.add_argument("--workers", type=int, default=3); ap.add_argument("--votes", default="3"); ap.add_argument("--scene", default=None)
    a = ap.parse_args()
    d = O / f"rvs_{a.tag}_{a.round}"
    if not d.is_dir():
        sys.exit(f"no snapshot {d}")
    rooms = sorted({m.group(1) for p in d.glob("*_wide*.png") if (m := re.match(r"(.+?)_wide\w*$", p.stem))})
    if a.rooms:
        rooms = [r for r in rooms if r in a.rooms.split(",")]
    prev = prev_round(a.tag, a.round); gt = O / f"gt_{a.tag}_{a.round}"
    out = REPO / "out/vlm_review" / f"{a.tag}_{a.round}"; out.mkdir(parents=True, exist_ok=True)

    def run(room):
        cmd = [sys.executable, str(HERE / "vlm_review.py"), "--scene", a.scene or a.tag, "--round", a.round, "--room", room, "--views", str(d),
               "--max-views", a.max_views, "--votes", a.votes, "--out", str(out / f"{room}.json")]
        if prev:
            cmd += ["--prev", str(prev)]
        if gt.is_dir():
            cmd += ["--gt", str(gt)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        return (r.stdout.strip() or r.stderr.strip()[-300:]).splitlines()[-1] if (r.stdout or r.stderr) else f"{room}: no output"

    with ThreadPoolExecutor(a.workers) as ex:
        for line in ex.map(run, rooms):
            print(line, flush=True)


if __name__ == "__main__":
    main()
