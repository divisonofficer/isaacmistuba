"""Optional LLM paraphrase layer for instruction generation.

Augments the deterministic template instructions with more varied, fluent English
using ``codex-as-api`` (ChatGPT-account OAuth login, ``~/.codex/auth.json``) via a
small bundled Node helper (``tools/codex_paraphrase/paraphrase.mjs``).

Everything here is best-effort: if Node, the helper, the ``codex-as-api`` install,
or the ChatGPT auth is missing — or the call errors / times out — the functions
return empty and the caller keeps the template-only instructions. Instruction
generation must NEVER fail because of this layer.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

Instruction = dict[str, Any]

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CHECK_TIMEOUT_S = 12
_PARAPHRASE_TIMEOUT_S = 60


def _helper_dir() -> Path:
    override = os.environ.get("ROBOMITUBA_CODEX_PARAPHRASE_DIR")
    return Path(override) if override else (_REPO_ROOT / "tools" / "codex_paraphrase")


def _helper_script() -> Path:
    return _helper_dir() / "paraphrase.mjs"


def _node_bin() -> str | None:
    env = os.environ.get("ROBOMITUBA_NODE")
    if env and Path(env).exists():
        return env
    found = shutil.which("node")
    if found:
        return found
    # nvm installs node outside the default PATH for non-login shells.
    candidates = sorted(glob.glob(str(Path.home() / ".nvm" / "versions" / "node" / "*" / "bin" / "node")), reverse=True)
    return candidates[0] if candidates else None


@lru_cache(maxsize=1)
def codex_available() -> bool:
    """True only when Node + helper + codex-as-api + ChatGPT auth are all present."""
    node = _node_bin()
    script = _helper_script()
    if not node or not script.is_file():
        return False
    if not (_helper_dir() / "node_modules" / "codex-as-api").exists():
        return False
    try:
        out = subprocess.run(
            [node, str(script), "--check"],
            cwd=str(_helper_dir()),
            capture_output=True, text=True, timeout=_CHECK_TIMEOUT_S,
        )
        if out.returncode != 0:
            return False
        return bool(json.loads(out.stdout or "{}").get("available"))
    except Exception:
        return False


def paraphrase(instructions: list[Instruction], *, n_variants: int = 2) -> list[Instruction]:
    """Return extra codex-paraphrased Instruction dicts, or [] on any failure.

    One subprocess call per episode: all distinct (type, level) template
    instructions are paraphrased together. Returned instructions carry
    ``source="codex"`` and ``grounding.paraphrase_of`` = the source type.
    """
    if not instructions or not codex_available():
        return []
    node = _node_bin()
    if not node:
        return []
    # One representative per (type, level) — no point paraphrasing duplicates.
    seen: set[tuple[str, str]] = set()
    payload_in: list[dict] = []
    base_by_type: dict[str, Instruction] = {}
    for ins in instructions:
        key = (str(ins.get("type")), str(ins.get("level")))
        if key in seen:
            continue
        seen.add(key)
        payload_in.append({"type": ins.get("type"), "level": ins.get("level"), "text": ins.get("text")})
        base_by_type[str(ins.get("type"))] = ins
    try:
        proc = subprocess.run(
            [node, str(_helper_script())],
            cwd=str(_helper_dir()),
            input=json.dumps({"instructions": payload_in, "n_variants": int(n_variants)}),
            capture_output=True, text=True, timeout=_PARAPHRASE_TIMEOUT_S,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        results = json.loads(proc.stdout).get("results") or []
    except Exception:
        return []

    out: list[Instruction] = []
    for r in results:
        rtype = str(r.get("type") or "")
        base = base_by_type.get(rtype, {})
        for variant in r.get("variants") or []:
            text = str(variant).strip()
            if not text:
                continue
            out.append({
                "type": rtype,
                "level": base.get("level", r.get("level", "")),
                "text": text,
                "lang": "en",
                "source": "codex",
                "grounding": {"paraphrase_of": rtype, **(base.get("grounding") or {})},
            })
    return out
