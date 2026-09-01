from __future__ import annotations

from contextvars import ContextVar, Token

_execution_workspace_id: ContextVar[int | None] = ContextVar(
    "execution_workspace_id", default=None
)


def current_execution_workspace_id() -> int | None:
    return _execution_workspace_id.get()


def bind_execution_workspace_id(workspace_id: int | None) -> Token[int | None]:
    return _execution_workspace_id.set(workspace_id)


def reset_execution_workspace_id(token: Token[int | None]) -> None:
    _execution_workspace_id.reset(token)
