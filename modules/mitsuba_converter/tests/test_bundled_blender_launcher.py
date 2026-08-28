"""Pure tests for bundled-Blender SONAME compatibility generation."""
from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[3] / "tools/infinigen/run_bundled_blender.py"
SPEC = importlib.util.spec_from_file_location("run_bundled_blender", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_compatibility_names_version_prefixes():
    assert MODULE.compatibility_names("libsycl.so.7.2.0-8") == [
        "libsycl.so.7",
        "libsycl.so.7.2",
    ]
    assert MODULE.compatibility_names("libOpenImageIO.so.2.5.16") == [
        "libOpenImageIO.so.2",
        "libOpenImageIO.so.2.5",
    ]


def test_compatibility_names_ignores_unversioned():
    assert MODULE.compatibility_names("libexample.so") == []
