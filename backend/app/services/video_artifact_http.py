from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class RangeNotSatisfiable(ValueError):
    """The requested byte range cannot be served."""


def parse_byte_range(value: str, total: int) -> ByteRange:
    if total < 1 or not value.startswith("bytes="):
        raise RangeNotSatisfiable
    specification = value[6:].strip()
    if not specification or "," in specification or "-" not in specification:
        raise RangeNotSatisfiable
    start_text, end_text = specification.split("-", 1)
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else total - 1
            if start < 0 or end < start or start >= total:
                raise RangeNotSatisfiable
            return ByteRange(start=start, end=min(end, total - 1))
        suffix = int(end_text)
        if suffix <= 0:
            raise RangeNotSatisfiable
        length = min(suffix, total)
        return ByteRange(start=total - length, end=total - 1)
    except ValueError as exc:
        raise RangeNotSatisfiable from exc


def stream_file(
    path: Path,
    *,
    start: int = 0,
    length: int | None = None,
) -> Iterator[bytes]:
    remaining = length
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining is None or remaining > 0:
            read_size = CHUNK_SIZE
            if remaining is not None:
                read_size = min(read_size, remaining)
            chunk = handle.read(read_size)
            if not chunk:
                break
            yield chunk
            if remaining is not None:
                remaining -= len(chunk)


def safe_artifact_filename(artifact_id: int, task_id: int, suffix: str) -> str:
    return f"video-artifact-{artifact_id}-task-{task_id}{suffix.lower()}"
