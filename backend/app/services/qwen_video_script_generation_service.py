from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.core.exceptions import AppError
from app.providers import TextGenerationProvider
from app.schemas.video_script_version import QwenScriptProviderOutput


def select_timed_narration(
    output: QwenScriptProviderOutput, *, max_words: int = 32
) -> str:
    """Select complete scene utterances that fit a short-video voiceover budget."""
    scenes = sorted(output.scenes, key=lambda item: item.sequence)
    if not scenes or max_words < 1:
        raise AppError("Qwen script has no usable narration", 422)

    edge_indices = [0]
    if len(scenes) > 1:
        edge_indices.append(len(scenes) - 1)
    middle_indices = sorted(
        range(1, max(1, len(scenes) - 1)),
        key=lambda index: (
            abs(((scenes[index].start_ms + scenes[index].end_ms) / 2 / 15000) - 0.5),
            scenes[index].sequence,
        ),
    )

    selected: set[int] = set()
    used_words = 0
    for index in [*edge_indices, *middle_indices]:
        word_count = len(scenes[index].narration.split())
        if word_count and used_words + word_count <= max_words:
            selected.add(index)
            used_words += word_count
    if not selected:
        raise AppError("Qwen narration cannot fit the 15-second budget", 422)
    return " ".join(scenes[index].narration for index in sorted(selected))


@dataclass(frozen=True, slots=True)
class QwenScriptGenerationResult:
    output: QwenScriptProviderOutput
    prompt_digest: str
    provider_response_digest: str


class QwenVideoScriptGenerationService:
    def __init__(self, provider: TextGenerationProvider) -> None:
        self.provider = provider

    def generate(
        self, prompt_snapshot: dict[str, object]
    ) -> QwenScriptGenerationResult:
        encoded_snapshot = json.dumps(
            prompt_snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        prompt = (
            "Create one 15-second vertical ecommerce video script from the frozen "
            "JSON input below. Return one JSON object with title, concept, hook, "
            "cta, and 1-12 scenes. Each scene must contain sequence, start_ms, "
            "end_ms, shot_type, visual_description, action_description, narration, "
            "and subtitle_draft. Sequence must start at 1 and be continuous; the "
            "timeline must start at 0, have no gaps or overlaps, and end at 15000. "
            "Keep the combined narration concise enough for 15 seconds at a "
            "natural speaking rate: English narration must contain no more than "
            "32 words, with equivalent brevity in other languages. "
            "Do not return source identities, digests, review state, activation, or "
            "top-level narration/subtitles. Frozen input: " + encoded_snapshot
        )
        response = self.provider.generate(prompt)
        try:
            output = QwenScriptProviderOutput.model_validate_json(response)
        except (ValidationError, ValueError) as error:
            raise AppError(
                "Qwen script output failed strict validation", 422
            ) from error
        select_timed_narration(output)
        return QwenScriptGenerationResult(
            output=output,
            prompt_digest=hashlib.sha256(prompt.encode()).hexdigest(),
            provider_response_digest=hashlib.sha256(response.encode()).hexdigest(),
        )
