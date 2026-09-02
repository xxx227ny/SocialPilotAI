from __future__ import annotations

import io
import wave
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings
from app.providers.live_configuration import (
    effective_qwen_api_key,
    effective_qwen_tts_endpoint,
)


class TtsExplicitFailure(RuntimeError):
    def __init__(self, message: str, *, category: str) -> None:
        super().__init__(message)
        self.category = category


class TtsSubmissionUnknown(RuntimeError):
    pass


class TtsProvider(Protocol):
    provider_name: str

    def generate(
        self, *, text: str, language: str, voice: str, rate: float
    ) -> bytes: ...


class QwenAudioTtsProvider:
    provider_name = "qwen_audio"
    _PLUS_SYSTEM_VOICES = frozenset({"longanlingxin", "longanlufeng"})

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        download_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.api_key = effective_qwen_api_key(settings)
        self.transport = transport
        self.download_transport = download_transport

    def generate(self, *, text: str, language: str, voice: str, rate: float) -> bytes:
        self.validate_request(text=text, language=language, voice=voice, rate=rate)
        selected_voice = voice or self.settings.qwen_tts_voice
        language_hint = language.split("-", 1)[0].lower()
        payload = {
            "model": self.settings.qwen_tts_model,
            "input": {
                "text": text.strip(),
                "voice": selected_voice,
                "format": "wav",
                "sample_rate": 48000,
                "rate": rate,
                "language_hints": [language_hint],
                "enable_aigc_tag": True,
            },
        }
        try:
            with httpx.Client(
                timeout=self.settings.qwen_tts_timeout,
                transport=self.transport,
            ) as client:
                response = client.post(
                    effective_qwen_tts_endpoint(self.settings),
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
        except httpx.ConnectError as exc:
            raise TtsExplicitFailure(
                "Qwen TTS connection failed", category="connection_failed"
            ) from exc
        except httpx.TimeoutException as exc:
            raise TtsSubmissionUnknown("Qwen TTS completion is unknown") from exc
        if response.status_code == 408 or response.status_code >= 500:
            raise TtsSubmissionUnknown("Qwen TTS completion is unknown")
        if response.is_error:
            category = {
                401: "credentials_rejected",
                403: "access_denied",
                429: "rate_limited",
            }.get(response.status_code, "request_rejected")
            raise TtsExplicitFailure("Qwen TTS request failed", category=category)
        try:
            body = response.json()
            audio_url = body["output"]["audio"]["url"]
        except (KeyError, TypeError, ValueError) as exc:
            raise TtsExplicitFailure(
                "Qwen TTS response is invalid", category="invalid_response"
            ) from exc
        if not self._approved_audio_url(audio_url):
            raise TtsExplicitFailure(
                "Qwen TTS response is invalid", category="invalid_response"
            )
        try:
            with httpx.Client(
                timeout=self.settings.qwen_tts_timeout,
                transport=self.download_transport,
            ) as client:
                audio_response = client.get(audio_url)
        except httpx.HTTPError as exc:
            raise TtsSubmissionUnknown("Qwen TTS audio delivery failed") from exc
        if audio_response.is_error:
            raise TtsSubmissionUnknown("Qwen TTS audio delivery failed")
        return self._canonical_stereo_wav(audio_response.content)

    def validate_request(
        self, *, text: str, language: str, voice: str, rate: float
    ) -> None:
        if not text.strip():
            raise TtsExplicitFailure("Narration is empty", category="invalid_input")
        if not self.api_key:
            raise TtsExplicitFailure(
                "Qwen TTS credentials are unavailable",
                category="credentials_unavailable",
            )
        selected_voice = voice or self.settings.qwen_tts_voice
        if (
            self.settings.qwen_tts_model == "qwen-audio-3.0-tts-plus"
            and selected_voice not in self._PLUS_SYSTEM_VOICES
            and not selected_voice.startswith("qwen-audio-3.0-tts-plus-")
        ):
            raise TtsExplicitFailure(
                "Qwen TTS voice is incompatible with the configured model",
                category="voice_model_mismatch",
            )

    @staticmethod
    def _approved_audio_url(value: object) -> bool:
        if not isinstance(value, str):
            return False
        try:
            parsed = urlsplit(value)
        except ValueError:
            return False
        host = (parsed.hostname or "").lower()
        return bool(
            parsed.scheme in {"http", "https"}
            and parsed.username is None
            and parsed.password is None
            and parsed.port in {None, 80, 443}
            and host.endswith(".oss-cn-beijing.aliyuncs.com")
        )

    @staticmethod
    def _canonical_stereo_wav(content: bytes) -> bytes:
        try:
            with wave.open(io.BytesIO(content), "rb") as source:
                channels = source.getnchannels()
                sample_width = source.getsampwidth()
                sample_rate = source.getframerate()
                frames = source.readframes(source.getnframes())
        except (EOFError, wave.Error) as exc:
            raise TtsExplicitFailure(
                "Qwen TTS audio is invalid", category="invalid_audio"
            ) from exc
        if channels not in {1, 2} or sample_width != 2 or sample_rate != 48000:
            raise TtsExplicitFailure(
                "Qwen TTS audio contract is invalid", category="invalid_audio_contract"
            )
        if not frames:
            raise TtsExplicitFailure("Qwen TTS audio is empty", category="empty_audio")
        if channels == 1:
            samples = memoryview(frames).cast("h")
            stereo = bytearray(len(frames) * 2)
            target = memoryview(stereo).cast("h")
            target[0::2] = samples
            target[1::2] = samples
            frames = bytes(stereo)
        output = io.BytesIO()
        with wave.open(output, "wb") as destination:
            destination.setnchannels(2)
            destination.setsampwidth(2)
            destination.setframerate(48000)
            destination.writeframes(frames)
        return output.getvalue()
