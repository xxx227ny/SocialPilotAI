from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal

VisualTaskStatus = Literal[
    "PENDING",
    "RUNNING",
    "SUCCEEDED",
    "FAILED",
    "CANCELED",
    "UNKNOWN",
]


@dataclass(frozen=True, slots=True)
class VisualGenerationRequest:
    prompt: str
    duration_seconds: int
    aspect_ratio: str
    resolution: str


@dataclass(frozen=True, slots=True)
class VisualTaskSubmission:
    provider_task_id: str
    provider_request_id: str | None
    status: VisualTaskStatus


@dataclass(frozen=True, slots=True)
class VisualTaskSnapshot:
    provider_task_id: str
    status: VisualTaskStatus
    provider_request_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    provider_output_url: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class VisualGenerationProvider(ABC):
    """Provider-neutral asynchronous visual generation contract."""

    @abstractmethod
    async def submit(
        self, request: VisualGenerationRequest
    ) -> VisualTaskSubmission:
        """Submit an asynchronous visual task."""

    @abstractmethod
    async def fetch(self, provider_task_id: str) -> VisualTaskSnapshot:
        """Fetch the current state of an existing visual task."""
