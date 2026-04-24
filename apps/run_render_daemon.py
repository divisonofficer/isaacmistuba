from __future__ import annotations

import argparse
import os
import sys
import time


def _check_runtime() -> None:
    """Fail fast if drjit/mitsuba can't import or were built for a different Python.

    Background: drjit ships a CPython-ABI binary extension. If the daemon is launched
    with an interpreter (e.g. conda 3.12) that doesn't match the version drjit was
    compiled for (3.10.x), every render fails with a confusing late-bound error.
    Catch it at startup with an actionable message instead.
    """
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
            "    PYTHONPATH=/home/jinnyeong/robomituba-build/mitsuba3/python /usr/bin/python3.10 apps/run_render_daemon.py",
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
    parser.add_argument("--variant", default="cuda_ad_spectral", help="Default Mitsuba variant.")
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
