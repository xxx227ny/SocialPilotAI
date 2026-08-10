from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.execution.handlers.qwen_copy_matrix import QwenCopyMatrixGenerateV1Handler
from app.execution.handlers.qwen_strategy import QwenStrategyGenerateV1Handler
from app.execution.handlers.qwen_video_project import (
    QwenVideoProjectGenerateV1Handler,
)
from app.execution.registry import ExecutionHandlerRegistry
from app.providers import QwenProvider, TextGenerationProvider


class LazyQwenProvider(TextGenerationProvider):
    """Construct the network adapter only after a confirmed Job is claimed."""

    def __init__(
        self,
        settings: Settings,
        provider_factory: Callable[[Settings], TextGenerationProvider] = QwenProvider,
    ) -> None:
        self.settings = settings
        self.provider_factory = provider_factory

    def generate(self, prompt: str) -> str:
        return self.provider_factory(self.settings).generate(prompt)


def build_execution_handler_registry(
    *,
    session_factory: Callable[[], Session],
    settings: Settings,
    qwen_provider_factory: Callable[[Settings], TextGenerationProvider] = QwenProvider,
) -> ExecutionHandlerRegistry:
    registry = ExecutionHandlerRegistry()
    registry.register(
        QwenStrategyGenerateV1Handler(
            session_factory=session_factory,
            provider=LazyQwenProvider(settings, qwen_provider_factory),
            settings=settings,
        )
    )
    registry.register(
        QwenCopyMatrixGenerateV1Handler(
            session_factory=session_factory,
            provider=LazyQwenProvider(settings, qwen_provider_factory),
            settings=settings,
        )
    )
    registry.register(
        QwenVideoProjectGenerateV1Handler(
            session_factory=session_factory,
            provider=LazyQwenProvider(settings, qwen_provider_factory),
            settings=settings,
        )
    )
    return registry
