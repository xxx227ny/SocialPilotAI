"""Text generation provider adapters."""

from app.providers.base import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderConnectionError,
    ProviderError,
    ProviderModelError,
    ProviderQuotaError,
    TextGenerationProvider,
)
from app.providers.qwen_provider import QwenProvider
from app.providers.visual_base import (
    VisualGenerationProvider,
    VisualGenerationRequest,
    VisualTaskSnapshot,
    VisualTaskSubmission,
)
from app.providers.wanx_provider import WanxProvider

__all__ = [
    "ProviderAuthenticationError",
    "ProviderConnectionError",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderModelError",
    "ProviderQuotaError",
    "QwenProvider",
    "TextGenerationProvider",
    "VisualGenerationProvider",
    "VisualGenerationRequest",
    "VisualTaskSnapshot",
    "VisualTaskSubmission",
    "WanxProvider",
]
