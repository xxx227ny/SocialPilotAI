from __future__ import annotations

import hashlib
import os
import tempfile
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

ALLOWED_VIDEO_CONTENT_TYPES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}


class VideoArtifactError(Exception):
    """Safe artifact fetch or storage failure."""

    def __init__(self, category: str, message: str) -> None:
        self.category = category
        self.safe_message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class FetchedVideo:
    content: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class StoredVideo:
    relative_path: str
    content_type: str
    size_bytes: int
    sha256: str


class ProviderOutputFetcher(ABC):
    @abstractmethod
    async def fetch(self, source_url: str) -> FetchedVideo:
        """Fetch a provider result without exposing its source URL."""


class HttpProviderOutputFetcher(ProviderOutputFetcher):
    def __init__(self, max_bytes: int, timeout: float) -> None:
        self.max_bytes = max_bytes
        self.timeout = timeout

    async def fetch(self, source_url: str) -> FetchedVideo:
        parsed = urlparse(source_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise VideoArtifactError(
                "invalid_provider_output",
                "Provider video location is not a valid HTTPS URL",
            )
        if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise VideoArtifactError(
                "invalid_provider_output",
                "Provider video location is not allowed",
            )
        try:
            async with (
                httpx.AsyncClient(
                    timeout=self.timeout,
                    follow_redirects=False,
                ) as client,
                client.stream("GET", source_url) as response,
            ):
                if response.is_error:
                    raise VideoArtifactError(
                        "artifact_persist_failed",
                        "Provider video could not be downloaded",
                    )
                content_type = _normalize_content_type(
                    response.headers.get("content-type")
                )
                _require_supported_content_type(content_type)
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > self.max_bytes:
                        raise VideoArtifactError(
                            "artifact_persist_failed",
                            "Provider video exceeds the configured size limit",
                        )
        except httpx.TimeoutException as exc:
            raise VideoArtifactError(
                "artifact_persist_failed",
                "Provider video download timed out",
            ) from exc
        except httpx.RequestError as exc:
            raise VideoArtifactError(
                "artifact_persist_failed",
                "Provider video download failed",
            ) from exc
        if not content:
            raise VideoArtifactError(
                "invalid_provider_output",
                "Provider video is empty",
            )
        return FetchedVideo(bytes(content), content_type)


class VideoArtifactStorage(ABC):
    @abstractmethod
    def store(
        self,
        *,
        task_id: int,
        content: bytes,
        content_type: str,
    ) -> StoredVideo:
        """Store one video atomically and return a safe relative path."""

    @abstractmethod
    def resolve(self, relative_path: str) -> tuple[Path, str]:
        """Resolve one controlled relative path for safe reading."""

    @abstractmethod
    def delete(self, relative_path: str) -> None:
        """Delete an owned file after a failed database finalization."""


class LocalVideoArtifactStorage(VideoArtifactStorage):
    def __init__(self, root: Path, max_bytes: int) -> None:
        if not root.is_absolute():
            raise VideoArtifactError(
                "artifact_storage_not_configured",
                "Artifact storage root must be an absolute path",
            )
        self.root = root.resolve()
        self.max_bytes = max_bytes

    def store(
        self,
        *,
        task_id: int,
        content: bytes,
        content_type: str,
    ) -> StoredVideo:
        normalized_type = _normalize_content_type(content_type)
        extension = _require_supported_content_type(normalized_type)
        if not content:
            raise VideoArtifactError(
                "invalid_provider_output",
                "Provider video is empty",
            )
        if len(content) > self.max_bytes:
            raise VideoArtifactError(
                "artifact_persist_failed",
                "Provider video exceeds the configured size limit",
            )
        digest = hashlib.sha256(content).hexdigest()
        filename = f"render-task-{task_id}-{digest[:16]}{extension}"
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self._safe_path(filename)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{filename}.",
            suffix=".tmp",
            dir=self.root,
        )
        try:
            with os.fdopen(handle, "wb") as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, destination)
        except Exception:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name)
            raise
        return StoredVideo(
            relative_path=filename,
            content_type=normalized_type,
            size_bytes=len(content),
            sha256=digest,
        )

    def store_immutable(
        self,
        *,
        task_id: int,
        content: bytes,
        content_type: str,
    ) -> tuple[StoredVideo, bool]:
        """Atomically create one content-addressed file without replacing it."""
        normalized_type = _normalize_content_type(content_type)
        extension = _require_supported_content_type(normalized_type)
        if not content:
            raise VideoArtifactError(
                "invalid_provider_output",
                "Provider video is empty",
            )
        if len(content) > self.max_bytes:
            raise VideoArtifactError(
                "artifact_persist_failed",
                "Provider video exceeds the configured size limit",
            )
        digest = hashlib.sha256(content).hexdigest()
        filename = f"render-task-{task_id}-{digest[:16]}{extension}"
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self._safe_path(filename)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{filename}.",
            suffix=".tmp",
            dir=self.root,
        )
        created = False
        try:
            with os.fdopen(handle, "wb") as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            try:
                os.link(temporary_name, destination)
                created = True
            except FileExistsError:
                if (
                    destination.stat().st_size != len(content)
                    or _sha256_file(destination) != digest
                ):
                    raise VideoArtifactError(
                        "artifact_persist_failed",
                        "Existing immutable artifact does not match content",
                    ) from None
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name)
        return (
            StoredVideo(
                relative_path=filename,
                content_type=normalized_type,
                size_bytes=len(content),
                sha256=digest,
            ),
            created,
        )

    def resolve(self, relative_path: str) -> tuple[Path, str]:
        candidate = self._safe_path(relative_path)
        if not candidate.is_file():
            raise VideoArtifactError(
                "not_found",
                "Stored video artifact is unavailable",
            )
        content_type = _content_type_for_suffix(candidate.suffix)
        return candidate, content_type

    def delete(self, relative_path: str) -> None:
        path = self._safe_path(relative_path)
        with suppress(FileNotFoundError):
            path.unlink()

    def _safe_path(self, relative_path: str) -> Path:
        supplied = Path(relative_path)
        if supplied.is_absolute() or len(supplied.parts) != 1:
            raise VideoArtifactError(
                "invalid_input",
                "Artifact path is outside controlled storage",
            )
        candidate = (self.root / supplied).resolve()
        if not candidate.is_relative_to(self.root):
            raise VideoArtifactError(
                "invalid_input",
                "Artifact path is outside controlled storage",
            )
        return candidate


def _normalize_content_type(value: str | None) -> str:
    return (value or "").split(";", 1)[0].strip().lower()


def _require_supported_content_type(content_type: str) -> str:
    extension = ALLOWED_VIDEO_CONTENT_TYPES.get(content_type)
    if extension is None:
        raise VideoArtifactError(
            "invalid_provider_output",
            "Provider video content type is not supported",
        )
    return extension


def _content_type_for_suffix(suffix: str) -> str:
    normalized = suffix.lower()
    for content_type, extension in ALLOWED_VIDEO_CONTENT_TYPES.items():
        if extension == normalized:
            return content_type
    raise VideoArtifactError(
        "invalid_input",
        "Stored artifact type is not supported",
    )


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
