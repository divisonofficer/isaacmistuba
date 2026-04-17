from __future__ import annotations

import json
import urllib.request
from pathlib import Path


ASSET_ROOT = Path(__file__).resolve().parent.parent
REFERENCE_ROOT = ASSET_ROOT / "reference" / "agilex_ugv_gazebo_sim"
SOURCE_URLS_PATH = REFERENCE_ROOT / "source_urls.json"
UPSTREAM_ROOT = REFERENCE_ROOT / "upstream"


def _load_sources() -> dict[str, object]:
    return json.loads(SOURCE_URLS_PATH.read_text(encoding="utf-8"))


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def main() -> None:
    sources = _load_sources()
    files = dict(sources.get("files") or {})
    if not files:
        raise RuntimeError(f"No files declared in {SOURCE_URLS_PATH}")

    UPSTREAM_ROOT.mkdir(parents=True, exist_ok=True)

    for name, url in sorted(files.items()):
        if not isinstance(url, str):
            raise RuntimeError(f"Invalid URL for {name!r}: {url!r}")
        target = UPSTREAM_ROOT / name
        data = _download(url)
        target.write_bytes(data)
        print(f"[fetch_official_mesh] wrote {target} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
