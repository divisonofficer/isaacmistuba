"""Run an OpticalNav render-scene sync without a listening render daemon.

Staging a scene's render XML, mesh cache and editor preview meshes is pure
filesystem work, but the only entry point used to be ``POST
/api/opticalnav/.../sync/render-scene``.  That made a routine local repair
depend on a daemon being up and reachable: when the daemon was down (or busy,
or mid-restart for a code change) there was no way to re-stage a scene at all,
and ``run_infinigen_import.sh`` could only print "open the scene in webui and
click Save Map" -- which is the same HTTP route.

``RenderDaemon.__init__`` starts no server and no worker thread; it only builds
the state the sync reads.  So the sync can run in-process against a daemon
instance used purely as that state container.  This module is the seam: callers
get a function and a plain result instead of an HTTP route and a private
method, and the daemon object stays an implementation detail that a later
refactor can replace without touching any caller.
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

#: Progress callbacks receive ``(done, total, stage, message)``.
ProgressCallback = Callable[[int, int, str, str], None]

#: Scene-local advisory lock.  The daemon serialises syncs with an in-process
#: RLock, which cannot see another process at all, so two stagings of one scene
#: would interleave their writes to render_scene.xml and mesh_cache.  This file
#: lock is the cross-process half; it is taken by every caller of
#: :func:`sync_render_scene` and is safe for the daemon to adopt later.
SYNC_LOCK_FILENAME = ".render_scene_sync.lock"


class RenderSceneSyncBusy(RuntimeError):
    """Another process is already staging this scene."""


@contextlib.contextmanager
def _scene_sync_lock(scene_dir: Path) -> Iterator[None]:
    lock_path = scene_dir / SYNC_LOCK_FILENAME
    handle = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise RenderSceneSyncBusy(
                    f"another process holds {lock_path}; wait for it to finish"
                ) from exc
            # A filesystem without flock support must not block a local repair.
            yield
            return
        try:
            os.write(handle, f"{os.getpid()}\n".encode("ascii"))
            os.ftruncate(handle, len(f"{os.getpid()}\n"))
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        with contextlib.suppress(OSError):
            os.close(handle)


def daemon_is_reachable(url: str = "http://127.0.0.1:8765", *, timeout: float = 3.0) -> bool:
    """Report whether a render daemon could sync this scene behind our back.

    The daemon's lock is process-local, so a UI "Sync" click during an
    in-process sync races us.  Callers use this to decide whether running
    headless is safe right now.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/api/opticalnav/projects", timeout=timeout):
            return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


@dataclass(frozen=True)
class RenderSceneSyncResult:
    """Outcome of one sync, independent of how it was invoked."""

    status_code: int
    body: dict[str, Any]
    overlay_shape_count: int = 0

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def mesh_stats(self) -> dict[str, Any]:
        stats = self.body.get("mesh_stats")
        return dict(stats) if isinstance(stats, Mapping) else {}

    @property
    def error(self) -> str | None:
        if self.ok:
            return None
        for key in ("error", "message", "detail"):
            value = self.body.get(key)
            if isinstance(value, str) and value:
                return value
        return f"sync failed with status {self.status_code}"


@dataclass
class _NullProgress:
    """Collects progress lines so a CLI can render them without a websocket."""

    lines: list[str] = field(default_factory=list)

    def __call__(self, done: int, total: int, stage: str, message: str) -> None:
        self.lines.append(f"[{stage}] {done}/{total} {message}".rstrip())


def sync_render_scene(
    repo_root: str | Path,
    project_id: str,
    scene_id: str,
    payload: Mapping[str, Any] | None = None,
    *,
    sync_job_id: str | None = None,
    progress_cb: ProgressCallback | None = None,
) -> RenderSceneSyncResult:
    """Stage ``scene_id``'s render scene in this process.

    ``payload`` accepts the same keys the HTTP route does (``camera_rig``,
    ``environment``, ``scene_variant_id``); omit it for a plain re-stage.

    The scene directory must already exist -- this restages what authoring
    produced, it does not import or author a scene.

    Raises :class:`RenderSceneSyncBusy` when another process holds the scene's
    sync lock.  A *daemon* sync is not covered by that lock (its own lock is
    process-local), so check :func:`daemon_is_reachable` first when one may be
    running against the same scene.
    """
    root = Path(repo_root).resolve()
    project_dir = root / "out" / "opticalnav" / str(project_id)
    scene_dir = project_dir / "scenes" / str(scene_id)
    if not scene_dir.is_dir():
        raise FileNotFoundError(f"scene workspace not found: {scene_dir}")

    # Imported lazily: render_daemon pulls in the renderer stack, and a caller
    # that only wants the dataclasses above should not pay for that.
    from .render_daemon import RenderDaemon

    with _scene_sync_lock(scene_dir):
        daemon = RenderDaemon(repo_root=root)
        outcome = daemon._sync_opticalnav_render_scene(  # noqa: SLF001 - documented seam
            project_dir,
            str(scene_id),
            dict(payload or {}),
            sync_job_id=sync_job_id,
            progress_cb=progress_cb,
        )
    return RenderSceneSyncResult(
        status_code=int(outcome.status_code),
        body=dict(outcome.body),
        overlay_shape_count=int(getattr(outcome, "overlay_shape_count", 0) or 0),
    )
