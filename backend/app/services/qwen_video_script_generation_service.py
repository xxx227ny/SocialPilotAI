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
    """Return every scene utterance, or reject a script that cannot fit."""
    scenes = sorted(output.scenes, key=lambda item: item.sequence)
    if not scenes or max_words < 1:
        raise AppError("Qwen script has no usable narration", 422)
    narration = " ".join(scene.narration.strip() for scene in scenes)
    if not narration or len(narration.split()) > max_words:
        raise AppError("Qwen narration cannot fit the 15-second budget", 422)
    return narration


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
            "cta, and exactly 4 scenes. Each scene must contain sequence, start_ms, "
            "end_ms, shot_type, visual_description, action_description, narration, "
            "and subtitle_draft. Sequence must start at 1 and be continuous; the "
            "Use this exact timeline and purpose: scene 1 is the hook from 0 to "
            "3000 ms; scene 2 actively operates the product from 3000 to 8000 ms; "
            "scene 3 visibly proves the remaining benefits from 8000 to 12000 ms; "
            "scene 4 gives the CTA from 12000 to 15000 ms. "
            "Every supplied product selling point must be communicated by a safe, "
            "visibly demonstrable scene and by that scene's narration. Include a "
            "clear hook, active product operation, benefit proof, and final CTA. "
            "Do not invent capabilities or claims absent from the frozen input. "
            "For every scene, subtitle_draft must exactly equal narration. Keep all "
            "English narration in each scene must contain 6-8 words, so all four "
            "scenes contain exactly 24-32 words total at a natural speaking rate. "
            "Use equivalent brevity in other languages. Count words before returning "
            "the JSON. Never omit a scene from the spoken narration. "
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
