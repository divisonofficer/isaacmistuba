from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path


SCRIPT = Path(__file__).parents[3] / "apps" / "download_office_carpet_pbr.py"
SPEC = importlib.util.spec_from_file_location("office_carpet_downloader", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_extract_and_lockfile_validation_are_idempotent(tmp_path):
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("Carpet_BaseColor_2K.jpg", b"base")
        output.writestr("Carpet_Roughness_2K.jpg", b"rough")
        output.writestr("Carpet_NormalGL_2K.jpg", b"normal")
    source = MODULE.ASSETS[0]
    maps = MODULE.extract_asset(source, archive, tmp_path)
    record = MODULE.make_record(source, archive, maps, tmp_path)
    payload = {"schema": MODULE.REGISTRY_SCHEMA, "registry_version": MODULE.REGISTRY_VERSION,
               "materials": [record] * 4}
    # Validation checks the four-record lock contract; use four isolated records
    # whose IDs are irrelevant to the file/provenance validation itself.
    MODULE.validate_registry(payload, tmp_path)
    assert MODULE.extract_asset(source, archive, tmp_path) == maps
    assert record["surface_family"] == "carpet"
    assert record["variant_contract"]["scale_policy"] == "physical_size_m_only_no_variant_scale"


def test_validation_rejects_map_corruption(tmp_path):
    archive = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("Carpet_BaseColor_2K.jpg", b"base")
        output.writestr("Carpet_Roughness_2K.jpg", b"rough")
        output.writestr("Carpet_NormalGL_2K.jpg", b"normal")
    source = MODULE.ASSETS[0]
    maps = MODULE.extract_asset(source, archive, tmp_path)
    record = MODULE.make_record(source, archive, maps, tmp_path)
    payload = {"schema": MODULE.REGISTRY_SCHEMA, "registry_version": MODULE.REGISTRY_VERSION,
               "materials": [record] * 4}
    (tmp_path / maps["roughness"]).write_bytes(b"corrupt")
    try:
        MODULE.validate_registry(payload, tmp_path)
    except ValueError as error:
        assert "SHA-256 mismatch" in str(error)
    else:  # pragma: no cover
        raise AssertionError("corrupt map was accepted")
