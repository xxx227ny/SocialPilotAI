import io
import wave

import httpx

from app.core.config import Settings
from app.providers.wanx_image_provider import WanxImageProvider
from app.services.tts_provider import QwenAudioTtsProvider


def _mono_wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(b"\x01\x00" * 4800)
    return output.getvalue()


def test_qwen_tts_uses_token_plan_once_and_canonicalizes_audio() -> None:
    calls = {"generation": 0, "download": 0}
    content = _mono_wav()

    def generate(request: httpx.Request) -> httpx.Response:
        calls["generation"] += 1
        assert request.url.path.endswith("/services/audio/tts/SpeechSynthesizer")
        assert request.headers["authorization"] == "Bearer fake-token-plan-key"
        return httpx.Response(
            200,
            json={
                "output": {
                    "audio": {
                        "url": "http://dashscope-result-bj.oss-cn-beijing.aliyuncs.com/audio.wav"
                    }
                },
                "usage": {"characters": 5},
                "request_id": "safe-request-id",
            },
        )

    def download(request: httpx.Request) -> httpx.Response:
        calls["download"] += 1
        assert "authorization" not in request.headers
        return httpx.Response(200, content=content)

    settings = Settings(qwen_api_key="fake-token-plan-key")
    provider = QwenAudioTtsProvider(
        settings,
        transport=httpx.MockTransport(generate),
        download_transport=httpx.MockTransport(download),
    )
    result = provider.generate(
        text="Hello", language="en-US", voice="longanhuan_v3.6", rate=1
    )
    with wave.open(io.BytesIO(result), "rb") as audio:
        assert audio.getnchannels() == 2
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 48000
        assert audio.getnframes() == 4800
    assert calls == {"generation": 1, "download": 1}
    assert (
        QwenAudioTtsProvider._approved_audio_url("http://evil.invalid/a.wav") is False
    )


def test_wanx_image_uses_token_plan_once_without_leaking_bearer() -> None:
    calls = {"generation": 0, "download": 0}
    image = b"\x89PNG\r\n\x1a\n" + b"demo"

    def generate(request: httpx.Request) -> httpx.Response:
        calls["generation"] += 1
        assert request.url.path.endswith(
            "/services/aigc/multimodal-generation/generation"
        )
        assert request.headers["authorization"] == "Bearer fake-token-plan-key"
        return httpx.Response(
            200,
            json={
                "output": {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"image": "https://signed.invalid/image.png"}
                                ]
                            }
                        }
                    ]
                },
                "request_id": "safe-request-id",
            },
        )

    def download(request: httpx.Request) -> httpx.Response:
        calls["download"] += 1
        assert "authorization" not in request.headers
        return httpx.Response(200, content=image)

    settings = Settings(wanx_api_key="fake-token-plan-key")
    generated = WanxImageProvider(
        settings,
        transport=httpx.MockTransport(generate),
        download_transport=httpx.MockTransport(download),
    ).generate("A premium product photograph")
    assert generated.content == image
    assert generated.request_id_digest is not None
    assert calls == {"generation": 1, "download": 1}
