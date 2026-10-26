"""Local create-only storage primitives for noncanonical review records.

Writers serialize through an exclusive directory lock. An abandoned lock is
never stolen automatically: inspect it and recover it explicitly after checking
that no writer is active. Publication uses a same-directory hard link so a
crash cannot expose a partially written final JSON file or overwrite a record.
"""
import contextlib
import json
import os
import tempfile
import time
from pathlib import Path


@contextlib.contextmanager
def store_lock(store, timeout=5.0):
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = store / '.intake.lock'
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir(mode=0o700)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError('Review store is locked; check for an active writer before recovering a stale lock')
            time.sleep(0.01)
    try:
        yield
    finally:
        lock.rmdir()


def atomic_json_create(path, value):
    """Publish complete UTF-8 JSON once; never replace an existing path.

    Requires a filesystem supporting hard links (including NTFS). If publication
    is unsupported or fails, fail closed and leave any existing record intact.
    The exclusive store lock must be held by a caller performing chain appends.
    """
    path = Path(path)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    descriptor, temporary = tempfile.mkstemp(prefix='.pending-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-filesystem link is atomic and raises FileExistsError on collision.
        os.link(temporary, path)
        # Flush directory metadata where supported. Failure after publication
        # must not cause a caller to think the record was never published.
        if os.name == 'posix':
            try:
                fd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            except OSError:
                pass
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return path
