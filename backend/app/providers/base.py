from abc import ABC, abstractmethod


class ProviderError(Exception):
    """Base exception for safe provider failures."""


class ProviderAuthenticationError(ProviderError):
    """Provider credentials are missing or rejected."""


class ProviderConnectionError(ProviderError):
    """Provider could not be reached before the configured timeout."""


class ProviderConfigurationError(ProviderError):
    """Provider configuration is missing or unsupported."""


class ProviderModelError(ProviderError):
    """Provider returned an unsuccessful or unusable model response."""


class TextGenerationProvider(ABC):
    """Provider-neutral synchronous text generation contract."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate text for a prompt or raise a safe ProviderError."""
