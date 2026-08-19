from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.contracts import ExecutionContext, HandlerResult
from app.services.tts_provider import (
    TtsExplicitFailure,
    TtsProvider,
    TtsSubmissionUnknown,
)
from app.services.voiceover_generation_service import (
    VOICEOVER_GENERATE_V1,
    VoiceoverExceedsTimeline,
    VoiceoverGenerationService,
)


class VoiceoverGenerateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    composition_id: int = Field(gt=0)
    script_version_id: int = Field(gt=0)
    product_id: int = Field(gt=0)
    narration_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    language: str
    voice: str
    speaking_rate: float
    target_duration_ms: int = Field(gt=0)


class VoiceoverGenerateV1Handler:
    job_type = VOICEOVER_GENERATE_V1
    input_schema = VoiceoverGenerateInput

    def __init__(
        self, *, session_factory, settings: Settings, provider: TtsProvider
    ) -> None:
        self.session_factory, self.settings, self.provider = (
            session_factory,
            settings,
            provider,
        )

    def execute(self, context: ExecutionContext, payload: BaseModel) -> HandlerResult:
        data = VoiceoverGenerateInput.model_validate(payload)
        context.before_provider_call(may_submit_external=True)
        try:
            with self.session_factory() as session:
                artifact = VoiceoverGenerationService(session, self.settings).generate(
                    composition_id=data.composition_id,
                    script_version_id=data.script_version_id,
                    narration_digest=data.narration_digest,
                    language=data.language,
                    voice=data.voice,
                    speaking_rate=data.speaking_rate,
                    target_duration_ms=data.target_duration_ms,
                    provider=self.provider,
                )
        except VoiceoverExceedsTimeline as exc:
            return HandlerResult.failed(
                "VOICEOVER_EXCEEDS_TIMELINE",
                safe_error_details={
                    "natural_duration_ms": exc.natural_duration_ms,
                    "target_duration_ms": exc.target_duration_ms,
                },
                provider_submission_state="RESPONSE_RECEIVED",
            )
        except TtsSubmissionUnknown:
            return HandlerResult.submit_unknown(
                "QWEN_TTS_RESULT_UNKNOWN", provider_name=self.provider.provider_name
            )
        except TtsExplicitFailure:
            return HandlerResult.failed(
                "QWEN_TTS_FAILED", provider_submission_state="EXPLICIT_FAILURE"
            )
        except AppError:
            return HandlerResult.failed(
                "QWEN_TTS_OUTPUT_INVALID",
                provider_submission_state="RESPONSE_RECEIVED",
            )
        return HandlerResult.succeeded(
            provider_name=self.provider.provider_name,
            result_entity_type="video_composition_audio_artifact",
            result_entity_id=artifact.id,
            provider_submission_state="RESPONSE_RECEIVED",
        )
