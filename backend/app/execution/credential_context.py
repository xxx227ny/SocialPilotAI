from contextvars import ContextVar, Token
from typing import cast

from app.core.provider_runtime import WorkspaceProviderRuntime

_UNBOUND = object()
_execution_api_key: ContextVar[str | None | object] = ContextVar(
    "execution_api_key", default=_UNBOUND
)
_execution_provider_runtime: ContextVar[WorkspaceProviderRuntime | None | object] = (
    ContextVar("execution_provider_runtime", default=_UNBOUND)
)


def current_execution_api_key() -> str | None:
    value = _execution_api_key.get()
    return cast(str | None, None if value is _UNBOUND else value)


def execution_api_key_is_bound() -> bool:
    return _execution_api_key.get() is not _UNBOUND


def bind_execution_api_key(api_key: str | None) -> Token[str | None | object]:
    return _execution_api_key.set(api_key)


def reset_execution_api_key(token: Token[str | None | object]) -> None:
    _execution_api_key.reset(token)


def current_execution_provider_runtime() -> WorkspaceProviderRuntime | None:
    value = _execution_provider_runtime.get()
    return cast(WorkspaceProviderRuntime | None, None if value is _UNBOUND else value)


def execution_provider_runtime_is_bound() -> bool:
    return _execution_provider_runtime.get() is not _UNBOUND


def bind_execution_provider_runtime(
    runtime: WorkspaceProviderRuntime | None,
) -> Token[WorkspaceProviderRuntime | None | object]:
    return _execution_provider_runtime.set(runtime)


def reset_execution_provider_runtime(
    token: Token[WorkspaceProviderRuntime | None | object],
) -> None:
    _execution_provider_runtime.reset(token)
