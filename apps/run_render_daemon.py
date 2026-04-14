from __future__ import annotations

import argparse
import time

from mitsuba_converter import serve_render_daemon
from robomituba_bridge import repo_root_from


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the robomituba warm render daemon and control plane.")
    parser.add_argument("--repo-root", default=None, help="Repository root. Defaults to auto-detected project root.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8765, help="Bind port. Defaults to 8765.")
    parser.add_argument("--variant", default="cuda_ad_spectral", help="Default Mitsuba variant.")
    args = parser.parse_args()

    repo_root = repo_root_from(args.repo_root)
    daemon = serve_render_daemon(repo_root=repo_root, host=args.host, port=args.port, variant=args.variant)
    print(f"Render daemon listening on {daemon.base_url}")
    print(f"Control plane home: {daemon.base_url}/")
    print(f"Repo root: {repo_root}")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("Shutting down render daemon...")
        daemon.shutdown()


if __name__ == "__main__":
    main()
