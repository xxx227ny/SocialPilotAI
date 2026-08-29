import asyncio
import json

import httpx
from pydantic import SecretStr

from app.core.config import Settings
from app.providers.base import (
    ProviderAuthenticationError,
    ProviderConnectionError,
)
from app.providers.visual_base import VisualGenerationRequest
from app.providers.wanx_provider import (
    WANX_PRODUCT_I2V_NEGATIVE_PROMPT,
    WanxProvider,
)

TEST_ENDPOINT = "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1"
TEST_KEY = "unit-test-wanx-key"


def provider_with_handler(handler) -> WanxProvider:
    app_settings = Settings(
        _env_file=None,
        wanx_api_key=SecretStr(TEST_KEY),
        wanx_endpoint=TEST_ENDPOINT,
        wanx_model="wan2.7-t2v",
        wanx_timeout=10,
    )
    return WanxProvider(
        app_settings,
        transport=httpx.MockTransport(handler),
    )


def test_submit_maps_request_and_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == (
            "/api/v1/services/aigc/video-generation/video-synthesis"
        )
        assert request.headers["X-DashScope-Async"] == "enable"
        assert request.headers["Authorization"] == f"Bearer {TEST_KEY}"
        body = json.loads(request.content)
        assert body == {
            "model": "wan2.7-t2v",
            "input": {"prompt": "Portable blender on an office desk."},
            "parameters": {
                "duration": 10,
                "ratio": "9:16",
                "resolution": "720P",
            },
        }
        return httpx.Response(
            200,
            json={
                "output": {
                    "task_id": "task123",
                    "task_status": "PENDING",
                },
                "request_id": "request123",
            },
        )

    provider = provider_with_handler(handler)
    result = asyncio.run(
        provider.submit(
            VisualGenerationRequest(
                prompt="Portable blender on an office desk.",
                duration_seconds=10,
                aspect_ratio="9:16",
                resolution="720P",
            )
        )
    )

    assert result.provider_task_id == "task123"
    assert result.provider_request_id == "request123"
    assert result.status == "PENDING"


def test_submit_maps_reference_image_to_real_i2v_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "wan2.6-i2v-flash"
        assert body["input"]["prompt"] == "Show the feeder dispensing food."
        assert body["input"]["img_url"] == "data:image/png;base64,iVBORw0KGgo="
        assert body["parameters"] == {
            "duration": 15,
            "resolution": "720P",
            "prompt_extend": True,
            "shot_type": "single",
            "negative_prompt": WANX_PRODUCT_I2V_NEGATIVE_PROMPT,
            "audio": False,
            "watermark": False,
        }
        return httpx.Response(
            200,
            json={"output": {"task_id": "i2v-1", "task_status": "PENDING"}},
        )

    from app.providers.visual_base import VisualReferenceImage

    result = asyncio.run(
        provider_with_handler(handler).submit(
            VisualGenerationRequest(
                prompt="Show the feeder dispensing food.",
                duration_seconds=15,
                aspect_ratio="9:16",
                resolution="720P",
                reference_images=(
                    VisualReferenceImage(
                        content=b"\x89PNG\r\n\x1a\n",
                        content_type="image/png",
                    ),
                ),
            )
        )
    )
    assert result.provider_task_id == "i2v-1"


def test_fetch_maps_succeeded_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/tasks/task123"
        assert request.headers["Authorization"] == f"Bearer {TEST_KEY}"
        assert "X-DashScope-Async" not in request.headers
        return httpx.Response(
            200,
            json={
                "request_id": "request456",
                "output": {
                    "task_id": "task123",
                    "task_status": "SUCCEEDED",
                    "submit_time": "2026-07-17 10:00:00.000",
                    "end_time": "2026-07-17 10:03:00.000",
                    "video_url": "https://provider.example/video.mp4",
                },
                "usage": {
                    "duration": 10,
                    "ratio": "9:16",
                    "SR": 720,
                },
            },
        )

    snapshot = asyncio.run(provider_with_handler(handler).fetch("task123"))

    assert snapshot.provider_task_id == "task123"
    assert snapshot.provider_request_id == "request456"
    assert snapshot.status == "SUCCEEDED"
    assert snapshot.provider_output_url == ("https://provider.example/video.mp4")
    assert snapshot.metadata["usage"] == {
        "duration": 10,
        "ratio": "9:16",
        "SR": 720,
    }


def test_authentication_failure_is_safe() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"code": "InvalidApiKey", "message": "secret response"},
        )

    provider = provider_with_handler(handler)

    try:
        asyncio.run(
            provider.submit(
                VisualGenerationRequest(
                    prompt="Safe prompt",
                    duration_seconds=5,
                    aspect_ratio="16:9",
                    resolution="720P",
                )
            )
        )
    except ProviderAuthenticationError as exc:
        message = str(exc)
        assert message == "Wanx authentication failed"
        assert TEST_KEY not in message
        assert "secret response" not in message
    else:
        raise AssertionError("Wanx 401 response should fail authentication")


def test_fetch_returns_failed_provider_status() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "request_id": "request789",
                "output": {
                    "task_id": "task123",
                    "task_status": "FAILED",
                    "code": "InvalidParameter",
                    "message": "The request parameter is invalid",
                },
            },
        )

    snapshot = asyncio.run(provider_with_handler(handler).fetch("task123"))

    assert snapshot.status == "FAILED"
    assert snapshot.error_code == "InvalidParameter"
    assert snapshot.error_message == "The request parameter is invalid"
    assert snapshot.provider_output_url is None


def test_timeout_uses_safe_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"upstream timeout with {TEST_KEY}", request=request)

    provider = provider_with_handler(handler)

    try:
        asyncio.run(provider.fetch("task123"))
    except ProviderConnectionError as exc:
        message = str(exc)
        assert message == "Wanx request timed out"
        assert TEST_KEY not in message
    else:
        raise AssertionError("Wanx timeout should raise a connection error")
