"""Reference-match ratio from a Codex pack: match / (match + missing + different), summed over rooms (user target 2026-10-26: >= 0.5).
  refs_ratio.py TAG_ROUND [...]            print the ratio per pack
  refs_ratio.py --gaps OUTDIR TAG_ROUND... write OUTDIR/<pack>.md: every missing/different item by room (the fix queue)"""
import json, sys
from pathlib import Path
Q = Path(__file__).resolve().parents[2] / "out/vlm_queue"

def load(pack):
    d = json.load(open(Q / pack / "refs_answer.json"))
    return {r: v for r, v in d.items() if isinstance(v, dict)}

def ratio(pack):
    d = load(pack); m = sum(len(v.get("matches", [])) for v in d.values())
    x = sum(len(v.get("missing", [])) for v in d.values()); y = sum(len(v.get("different", [])) for v in d.values())
    return m, x, y, m / max(1, m + x + y)

if __name__ == "__main__":
    a = sys.argv[1:]; out = None
    if a and a[0] == "--gaps":
        out = Path(a[1]); out.mkdir(parents=True, exist_ok=True); a = a[2:]
    for p in a:
        m, x, y, r = ratio(p); print(f"{p}: match={m} missing={x} different={y} ratio={r:.2f}  (need {max(0, int(0.5 * (m + x + y) + 0.999) - m)} more matches at the same item count)")
        if out:
            L = [f"# {p}: match={m} missing={x} different={y} ratio={r:.2f}  target >= 0.50\n"]
            for room, v in load(p).items():
                if v.get("missing") or v.get("different"):
                    L.append(f"\n## {room}")
                    L += [f"- MISSING: {i}" for i in v.get("missing", [])] + [f"- DIFFERENT: {i}" for i in v.get("different", [])]
            (out / f"{p}.md").write_text("\n".join(L) + "\n")
