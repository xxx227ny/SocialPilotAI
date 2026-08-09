from __future__ import annotations

import re

from app.execution.contracts import ExecutionHandlerAdapter

_JOB_TYPE = re.compile(r"^[a-z0-9_.-]{1,80}$")


class ExecutionHandlerRegistry:
    """Explicit registry with no prefix, reflection, or fallback matching."""

    def __init__(self) -> None:
        self._handlers: dict[str, ExecutionHandlerAdapter] = {}

    def register(self, handler: ExecutionHandlerAdapter) -> None:
        job_type = handler.job_type
        if _JOB_TYPE.fullmatch(job_type) is None:
            raise ValueError("Handler job_type must be an exact normalized value")
        if job_type in self._handlers:
            raise ValueError(f"Handler already registered for job type: {job_type}")
        self._handlers[job_type] = handler

    def resolve(self, job_type: str) -> ExecutionHandlerAdapter | None:
        return self._handlers.get(job_type)

    @property
    def job_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))
