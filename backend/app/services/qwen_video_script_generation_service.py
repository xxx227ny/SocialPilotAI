from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from app.core.exceptions import AppError
from app.providers import TextGenerationProvider
from app.schemas.video_script_version import QwenScriptProviderOutput

TIMED_FOUR_ACT_SCENE_COUNT = 4
_CJK_CHARACTER = re.compile(r"[\u3400-\u9fff]")
_LATIN_WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
_SPOKEN_UNIT = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")


def _spoken_units(value: str) -> int:
    """Estimate spoken density for mixed Chinese and Latin narration."""
    return len(_CJK_CHARACTER.findall(value)) + len(_LATIN_WORD.findall(value))


def _truncate_spoken_units(value: str, maximum: int) -> str:
    stripped = value.strip()
    matches = tuple(_SPOKEN_UNIT.finditer(stripped))
    if len(matches) <= maximum:
        return stripped
    shortened = stripped[: matches[maximum - 1].end()].rstrip(" ,，、;；:：.!！?？")
    return shortened + ("。" if _CJK_CHARACTER.search(shortened) else ".")


def normalize_timed_four_act_narration(
    output: QwenScriptProviderOutput, *, english: bool
) -> QwenScriptProviderOutput:
    """Fit overlong provider narration to each frozen scene without cutting audio."""
    scenes = sorted(output.scenes, key=lambda item: item.sequence)
    normalized = []
    chinese_maximums = (14, 22, 18, 14)
    for index, scene in enumerate(scenes):
        narration = scene.narration.strip()
        if english:
            words = narration.split()
            if len(words) < 6:
                raise AppError("Qwen narration failed the per-scene word budget", 422)
            if len(words) > 8:
                narration = " ".join(words[:8]).rstrip(" ,;:.!?") + "."
        else:
            units = _spoken_units(narration)
            if units < 4:
                raise AppError("Qwen narration failed the per-scene speech budget", 422)
            narration = _truncate_spoken_units(narration, chinese_maximums[index])
        normalized.append(
            scene.model_copy(
                update={"narration": narration, "subtitle_draft": narration}
            )
        )
    return output.model_copy(update={"scenes": normalized})


def select_timed_narration(
    output: QwenScriptProviderOutput, *, min_words: int = 1, max_words: int = 32
) -> str:
    """Return every scene utterance, or reject a script that cannot fit."""
    scenes = sorted(output.scenes, key=lambda item: item.sequence)
    if not scenes or min_words < 1 or max_words < min_words:
        raise AppError("Qwen script has no usable narration", 422)
    narration = " ".join(scene.narration.strip() for scene in scenes)
    word_count = len(narration.split())
    if not narration or not min_words <= word_count <= max_words:
        raise AppError("Qwen narration cannot fit the 15-second budget", 422)
    return narration


def validate_timed_four_act_contract(
    output: QwenScriptProviderOutput, *, english: bool
) -> None:
    scenes = sorted(output.scenes, key=lambda item: item.sequence)
    expected = (
        (1, 0, 3000),
        (2, 3000, 8000),
        (3, 8000, 12000),
        (4, 12000, 15000),
    )
    actual = tuple((scene.sequence, scene.start_ms, scene.end_ms) for scene in scenes)
    if actual != expected:
        raise AppError("Qwen script failed the timed four-act contract", 422)
    if any(scene.subtitle_draft.strip() != scene.narration.strip() for scene in scenes):
        raise AppError("Qwen subtitles must match narration", 422)
    if english and any(not 6 <= len(scene.narration.split()) <= 8 for scene in scenes):
        raise AppError("Qwen narration failed the per-scene word budget", 422)
    if not english:
        scene_units = tuple(_spoken_units(scene.narration) for scene in scenes)
        per_scene_maximums = (16, 24, 20, 16)
        if any(
            not 4 <= units <= maximum
            for units, maximum in zip(scene_units, per_scene_maximums, strict=True)
        ):
            raise AppError("Qwen narration failed the per-scene speech budget", 422)
        if sum(scene_units) > 68:
            raise AppError("Qwen narration failed the total speech budget", 422)


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
            "For every scene, subtitle_draft must exactly equal narration. "
            "English narration in each scene must contain 6-8 words, so all four "
            "scenes contain exactly 24-32 words total at a natural speaking rate. "
            "For Chinese narration, use 4-14 spoken units in scene 1, 4-22 in "
            "scene 2, 4-18 in scene 3, and 4-14 in scene 4, with no more than "
            "60 spoken Chinese characters or Latin words total. "
            "Use equivalent brevity in other languages. Count the spoken units before "
            "returning the JSON. Never omit a scene from the spoken narration. "
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
        language = str(prompt_snapshot.get("language", "")).strip().lower()
        english = language == "en" or language.startswith("en-")
        output = normalize_timed_four_act_narration(output, english=english)
        validate_timed_four_act_contract(output, english=english)
        select_timed_narration(output, min_words=24 if english else 1)
        return QwenScriptGenerationResult(
            output=output,
            prompt_digest=hashlib.sha256(prompt.encode()).hexdigest(),
            provider_response_digest=hashlib.sha256(response.encode()).hexdigest(),
        )
