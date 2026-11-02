"""Resolve every 'proc:' src of catalog.FURNITURE / LIVED_IN to a factory class, the way realize._cls does (proc_assets first, then PROP_MODULES, else the module list of this file).
Run with the infinigen python from tools/infinigen:   /root/miniconda3/envs/infinigen/bin/python -m room_planner.check_catalog_srcs   -> exit 1 and a list when a name is missing.
Use it before sending any diff that touches the catalog or the module list (a dry-run patch does not catch a missing factory)."""
import importlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
src = (Path(__file__).parent / "realize.py").read_text()
m = re.search(r"PROP_MODULES\s*=\s*\[([^\]]*)\]", src)
mods = re.findall(r"\"(\w+)\"", m.group(1)) if m else ["proc_bookstore", "proc_boutique_flagship", "proc_rooftop", "proc_winepub", "proc_clinic_lobby", "proc_museum"]
from room_planner import catalog, proc_assets  # noqa: E402

missing = []
for table in ("FURNITURE", "LIVED_IN"):
    for key, e in getattr(catalog, table, {}).items():
        kind, _, name = e["src"].partition(":")
        if kind != "proc" or hasattr(proc_assets, name):
            continue
        if not any(hasattr(importlib.import_module("room_planner." + mn), name) for mn in mods):
            missing.append((table, key, name))
print("PROP_MODULES", mods)
print("MISSING", missing)
sys.exit(1 if missing else 0)
