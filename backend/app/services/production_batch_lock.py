"""Cross-process batch controls for the single-host SQLite deployment.

Keep the lock file in place: unlinking it could let waiters lock different inodes.
The OS releases locks when a process exits, so there is no stale lease to steal.
"""

import hashlib
import os
import tempfile
import time
from functools import wraps
from pathlib import Path

from app.core.exceptions import AppError


def serialized_batch_control(method):
    @wraps(method)
    def guarded(self, product_id, batch_id, *args, **kwargs):
        bind = self.session.get_bind()
        url = bind.engine.url
        if url.get_backend_name() != "sqlite":
            raise AppError("Production batch locking requires SQLite", 503)
        database = url.database
        identity = (
            str(Path(database).resolve())
            if database and database != ":memory:"
            else f"memory:{id(bind.engine)}"
        )
        directory = (
            Path(database).resolve().parent / ".production-locks"
            if database and database != ":memory:"
            else Path(tempfile.gettempdir()) / "socialpilot-production-locks"
        )
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        key = hashlib.sha256(f"{identity}:{batch_id}".encode()).hexdigest()
        with (directory / f"{key}.lock").open("a+b") as handle:
            if handle.seek(0, 2) == 0:
                handle.write(b"0")
                handle.flush()
            deadline = time.monotonic() + 5
            while True:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise AppError(
                            "Production batch is busy; retry shortly", 409
                        ) from None
                    time.sleep(0.05)
            try:
                # A request may have loaded the batch before it acquired the lock.
                self.session.flush()
                self.session.expire_all()
                return method(self, product_id, batch_id, *args, **kwargs)
            except Exception:
                self.session.rollback()
                raise
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    return guarded
