"""Public-domain paintings for Infinigen wall art (user 2026-10-13: the procedural `Art` patches read as finger painting).

Art Institute of Chicago open access: public-domain works are released under CC0 (https://www.artic.edu/open-access).
Writes data/wall_art_cc0/<id>.jpg (IIIF 843 px wide) and manifest.json with title / artist / date / aspect / source per image.

    python3 tools/infinigen/fetch_cc0_wall_art.py [--count 200]
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "data/wall_art_cc0"
API = "https://api.artic.edu/api/v1/artworks/search"
FIELDS = "id,title,artist_title,date_display,image_id,thumbnail,style_title,is_public_domain,classification_title"
UA = {"User-Agent": "robomituba-wall-art/1.0 (research dataset)", "AIC-User-Agent": "robomituba-wall-art/1.0"}


def get(url: str, data: bytes | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers={**UA, **({"Content-Type": "application/json"} if data else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def search(page: int, limit: int = 100) -> list[dict]:
    q = {"query": {"bool": {"must": [{"term": {"is_public_domain": True}}, {"term": {"classification_title.keyword": "painting"}},
                                     {"exists": {"field": "image_id"}}]}},
         "fields": FIELDS.split(","), "limit": limit, "page": page, "sort": [{"_score": "desc"}]}
    return json.loads(get(API, json.dumps(q).encode()))["data"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=200)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    man_path = OUT / "manifest.json"
    man = json.loads(man_path.read_text()) if man_path.is_file() else {"license": "CC0 1.0 (Art Institute of Chicago open access)", "images": []}
    have = {i["id"] for i in man["images"]}
    page = 1
    while len(man["images"]) < a.count and page <= 20:
        for w in search(page):
            if len(man["images"]) >= a.count:
                break
            if w["id"] in have or not w.get("is_public_domain") or not w.get("image_id"):
                continue
            th = w.get("thumbnail") or {}
            aspect = (th.get("width") or 0) / (th.get("height") or 1)
            if not 0.4 < aspect < 2.5:
                continue
            dst = OUT / f"{w['id']}.jpg"
            try:
                dst.write_bytes(get(f"https://www.artic.edu/iiif/2/{w['image_id']}/full/843,/0/default.jpg"))
            except Exception as exc:  # one bad image is not a reason to stop
                print("skip", w["id"], exc, flush=True)
                continue
            man["images"].append({"id": w["id"], "file": dst.name, "title": w["title"], "artist": w.get("artist_title"),
                                  "date": w.get("date_display"), "style": w.get("style_title"), "aspect": round(aspect, 4),
                                  "source": f"https://www.artic.edu/artworks/{w['id']}"})
            have.add(w["id"])
            time.sleep(0.2)
        page += 1
        man_path.write_text(json.dumps(man, indent=1))
    print(json.dumps({"images": len(man["images"]), "out": str(OUT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
