from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import AppError


@dataclass(frozen=True, slots=True)
class StoredCompositionAsset:
    relative_path: str
    size_bytes: int
    sha256: str
    created: bool


class VideoCompositionAssetStorage:
    AUDIO_TYPES = {
        "audio/wav": {".wav"},
        "audio/mpeg": {".mp3"},
        "audio/mp4": {".m4a", ".mp4"},
        "audio/x-m4a": {".m4a"},
    }

    def __init__(self, root: Path, max_bytes: int) -> None:
        if not root.is_absolute():
            raise AppError("Artifact storage is not configured", 503)
        self.root = root.resolve()
        self.max_bytes = max_bytes

    def resolve_audio(
        self, relative_path: str, content_type: str, size_bytes: int, sha256: str
    ) -> Path:
        path = self._path(relative_path)
        allowed = self.AUDIO_TYPES.get(content_type)
        if (
            allowed is None
            or path.suffix.casefold() not in allowed
            or not path.is_file()
            or path.stat().st_size != size_bytes
            or self.sha256(path) != sha256
        ):
            raise AppError("Composition audio artifact integrity check failed", 409)
        return path

    def store_immutable(
        self, *, identity: str, content: bytes, extension: str
    ) -> StoredCompositionAsset:
        if not content or len(content) > self.max_bytes:
            raise AppError("Composition asset cannot be persisted", 500)
        if extension not in {".mp4", ".vtt"}:
            raise AppError("Composition asset type is invalid", 500)
        digest = hashlib.sha256(content).hexdigest()
        filename = f"{identity}-{digest[:16]}{extension}"
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self._path(filename)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{filename}.", suffix=".tmp", dir=self.root
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
                    or self.sha256(destination) != digest
                ):
                    raise AppError(
                        "Immutable composition asset conflict", 500
                    ) from None
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name)
        return StoredCompositionAsset(filename, len(content), digest, created)

    def resolve_exact(
        self, relative_path: str, size_bytes: int, sha256: str, extension: str
    ) -> Path:
        path = self._path(relative_path)
        if (
            path.suffix.casefold() != extension
            or not path.is_file()
            or path.stat().st_size != size_bytes
            or self.sha256(path) != sha256
        ):
            raise AppError("Composition artifact integrity check failed", 409)
        return path

    def delete(self, relative_path: str) -> None:
        with suppress(FileNotFoundError):
            self._path(relative_path).unlink()

    def _path(self, relative_path: str) -> Path:
        supplied = Path(relative_path)
        if supplied.is_absolute() or len(supplied.parts) != 1:
            raise AppError("Artifact path is outside controlled storage", 409)
        candidate = (self.root / supplied).resolve()
        if not candidate.is_relative_to(self.root):
            raise AppError("Artifact path is outside controlled storage", 409)
        return candidate

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
