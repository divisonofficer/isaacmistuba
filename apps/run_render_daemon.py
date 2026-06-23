from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def _bootstrap_project_sys_path() -> None:
    """Add modules/*/src directories to sys.path so the daemon process can
    import local module packages without an editable
    install. Idempotent; safe to call multiple times.

    Without this the launcher only worked when the operator had previously
    run ``pip install -e modules/mitsuba_converter`` (or set PYTHONPATH
    manually) — fresh conda envs hit ``ModuleNotFoundError`` immediately.
    """
    repo_root = Path(__file__).resolve().parents[1]
    modules_root = repo_root / "modules"
    for sub in ("mitsuba_converter", "robomituba_bridge", "navigation_dataset"):
        src = modules_root / sub / "src"
        if src.is_dir():
            src_str = str(src)
            if src_str not in sys.path:
                sys.path.insert(0, src_str)


_bootstrap_project_sys_path()


def _raise_nofile_to_hard() -> None:
    """Bump RLIMIT_NOFILE soft → hard so a sweep peak doesn't EMFILE-fail.

    Launchers that come from a parent shell with the legacy 1024 fd soft cap
    (e.g. some systemd / npm-spawn paths) would otherwise let `_persist_request`
    crash mid-sweep with `OSError: [Errno 24] Too many open files`. Raising
    soft → hard is allowed without privileges and is harmless when soft is
    already at hard. Best-effort: skip on platforms without `resource` (Windows).
    """
    try:
        import resource  # POSIX only
    except ImportError:
        return
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft < hard:
            resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
            print(
                f"[run_render_daemon] RLIMIT_NOFILE raised: {soft} → {hard}",
                file=sys.stderr, flush=True,
            )
    except (OSError, ValueError) as exc:
        print(f"[run_render_daemon] RLIMIT_NOFILE raise skipped: {exc}",
              file=sys.stderr, flush=True)


_raise_nofile_to_hard()


def _is_subprocess_mode() -> bool:
    """Phase R: daemon process does not import mitsuba when the worker
    subprocess does it for us. Decided by the same env flag the daemon
    code itself reads.
    """
    raw = os.environ.get("ROBOMITUBA_RENDER_INPROCESS", "0").strip().lower()
    # default "0" (subprocess isolation) — only explicit on values use
    # the legacy in-process render thread.
    return raw in ("0", "false", "no", "off")


def _check_runtime() -> None:
    """Fail fast if drjit/mitsuba can't import or were built for a different Python.

    Background: drjit ships a CPython-ABI binary extension. If the daemon is launched
    with an interpreter (e.g. conda 3.12) that doesn't match the version drjit was
    compiled for (3.10.x), every render fails with a confusing late-bound error.
    Catch it at startup with an actionable message instead.

    Phase R skip: in subprocess mode (``ROBOMITUBA_RENDER_INPROCESS=0``) the
    daemon process never imports mitsuba — the worker subprocess does, with
    its own (possibly alternate) Python interpreter (see
    ``ROBOMITUBA_MITSUBA_PYTHON``). Skipping this probe lets the daemon
    launch on a base conda env that has no mitsuba at all.
    """
    if _is_subprocess_mode():
        print(
            "[run_render_daemon] subprocess mode (ROBOMITUBA_RENDER_INPROCESS=0): "
            "skipping daemon-side drjit/mitsuba import probe; worker subprocess "
            "will surface variant availability via its `ready` event.",
            file=sys.stderr, flush=True,
        )
        return
    try:
        import drjit  # type: ignore
        import mitsuba  # type: ignore
    except ImportError as exc:
        msg = str(exc)
        print(f"[run_render_daemon] FATAL: cannot import drjit/mitsuba: {msg}", file=sys.stderr, flush=True)
        print(
            f"[run_render_daemon] interpreter: {sys.executable} ({sys.version.split()[0]})",
            file=sys.stderr,
            flush=True,
        )
        print(
            "[run_render_daemon] Re-launch with the interpreter drjit was built for, e.g.\n"
            "    PYTHONPATH=/home/jinnyeong/robomituba-build/mitsuba3/python /usr/bin/python3.10 apps/run_render_daemon.py\n"
            "[run_render_daemon] Or run subprocess mode: ROBOMITUBA_RENDER_INPROCESS=0",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(2)


def main() -> None:
    _check_runtime()

    from mitsuba_converter import serve_render_daemon
    from robomituba_bridge import repo_root_from

    parser = argparse.ArgumentParser(description="Run the robomituba warm render daemon and control plane.")
    parser.add_argument("--repo-root", default=None, help="Repository root. Defaults to auto-detected project root.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8765, help="Bind port. Defaults to 8765.")
    parser.add_argument(
        "--variant",
        default=os.environ.get("ROBOMITUBA_MITSUBA_VARIANT", "auto"),
        help="Default Mitsuba variant, or 'auto' to pick a compatible runtime variant.",
    )
    args = parser.parse_args()

    repo_root = repo_root_from(args.repo_root)
    daemon = serve_render_daemon(repo_root=repo_root, host=args.host, port=args.port, variant=args.variant)
    print(f"Render daemon listening on {daemon.base_url}", flush=True)
    print(f"Control plane home: {daemon.base_url}/", flush=True)
    print(f"Repo root: {repo_root}", flush=True)
    print(f"Interpreter: {sys.executable} ({sys.version.split()[0]})", flush=True)
    sub_py = os.environ.get("ROBOMITUBA_PYTHON")
    if sub_py:
        print(f"Sub-process python (ROBOMITUBA_PYTHON): {sub_py}", flush=True)
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Shutting down render daemon...", flush=True)
        daemon.shutdown()


if __name__ == "__main__":
    main()
