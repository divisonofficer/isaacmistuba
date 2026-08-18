#!/usr/bin/env python3
"""Launch the repository-bundled Blender with generated SONAME compatibility links.

The bundled Blender libraries contain fully-versioned files such as
``libsycl.so.7.2.0-8`` but omit loader names such as ``libsycl.so.7``.  Generate the
missing version-prefix symlinks in a disposable directory, prepend it to
``LD_LIBRARY_PATH``, then replace this process with Blender.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
DEFAULT_BLENDER_DIR = REPO / "modules/infinigen/blender-4.2.0-linux-x64"
DEFAULT_COMPAT_DIR = Path("/tmp/robomituba-blender-libcompat")


def compatibility_names(filename: str) -> list[str]:
    """Return loader-version prefixes for a fully-versioned shared library name."""
    match = re.match(r"^(?P<stem>.+\.so)\.(?P<version>.+)$", filename)
    if not match:
        return []
    stem = match.group("stem")
    parts = match.group("version").split(".")
    names = []
    for end in range(1, len(parts)):
        prefix = ".".join(parts[:end])
        # Keep ABI-style numeric prefixes; package suffixes belong only to targets.
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", prefix):
            names.append(f"{stem}.{prefix}")
    return names


def prepare_compat(lib_dir: Path, compat_dir: Path) -> int:
    compat_dir.mkdir(parents=True, exist_ok=True)
    created = 0
    for source in sorted(lib_dir.glob("*.so.*")):
        for name in compatibility_names(source.name):
            link = compat_dir / name
            if link.exists() or link.is_symlink():
                continue
            link.symlink_to(source)
            created += 1
    return created


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--blender-dir", type=Path, default=DEFAULT_BLENDER_DIR)
    parser.add_argument("--compat-dir", type=Path, default=DEFAULT_COMPAT_DIR)
    known, blender_args = parser.parse_known_args()
    blender = known.blender_dir / "blender"
    lib_dir = known.blender_dir / "lib"
    if not blender.is_file():
        raise FileNotFoundError(blender)
    prepare_compat(lib_dir, known.compat_dir)
    env = os.environ.copy()
    existing = env.get("LD_LIBRARY_PATH")
    paths = [str(known.compat_dir), str(lib_dir)]
    if existing:
        paths.append(existing)
    env["LD_LIBRARY_PATH"] = os.pathsep.join(paths)
    os.execvpe(str(blender), [str(blender), *blender_args], env)


if __name__ == "__main__":
    main()
