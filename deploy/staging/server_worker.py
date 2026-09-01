"""Staging execution-worker entry."""

import server_runtime  # noqa: F401
from app.cli.execution_worker import main


if __name__ == "__main__":
    raise SystemExit(main())
