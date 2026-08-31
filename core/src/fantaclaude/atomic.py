"""One way to write a file the auction cannot afford to tear.

From the moment the admin closes FantaAstaLive until the transfer into the
lega is confirmed, data/asta-state.json is the only record of what the
room paid, and data/adjustments.yml is the one shared file three surfaces
write. Both are written the way the MCP writes its token cache: a temp file
in the target's own directory, fsynced, then os.replace over the target --
a reader sees the old file or the new one and never a torn one, and a
crash mid-write leaves the old file standing.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_atomic(path: Path, data: bytes, *, mode: int = 0o644) -> None:
    """Write `data` to `path` so a reader only ever sees the old contents or
    the new ones, never a torn file, and a crash mid-write leaves the old
    file standing untouched.

    The rename itself is not the whole story: POSIX does not guarantee a
    directory entry updated by os.replace() has reached disk just because
    the call returned, so after the replace this also fsyncs the
    *directory* -- closing the gap where a crash right after a successful
    return could still revert to the previous version. That directory
    fsync is allowed to raise rather than being swallowed as best-effort:
    the rename has already happened by then (there is no temp file left to
    clean up), and a failure at that point means the filesystem itself is
    faulted, which is worth surfacing loudly rather than reporting a write
    as durable when it was not.

    This is still not a power-loss guarantee everywhere: on macOS,
    os.fsync() does not flush the drive's own write cache (that needs
    F_FULLFSYNC, out of scope here), so a power cut can in principle still
    lose a write that fsync() reported as synced. What this function does
    guarantee, on every platform, is atomicity -- no reader ever observes a
    partially written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)
