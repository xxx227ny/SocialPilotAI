from contextvars import ContextVar, Token
from typing import cast

_UNBOUND = object()
_execution_api_key: ContextVar[str | None | object] = ContextVar(
    "execution_api_key", default=_UNBOUND
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
