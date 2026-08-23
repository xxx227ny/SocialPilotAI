from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.providers.live_configuration import effective_wanx_api_key


class WanxImageExplicitFailure(RuntimeError):
    pass


class WanxImageSubmissionUnknown(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GeneratedWanxImage:
    content: bytes
    request_id_digest: str | None


class WanxImageProvider:
    provider_name = "wanx"

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        download_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.api_key = effective_wanx_api_key(settings)
        self.transport = transport
        self.download_transport = download_transport

    def generate(
        self, prompt: str, *, reference_image: bytes | None = None
    ) -> GeneratedWanxImage:
        if not self.api_key:
            raise WanxImageExplicitFailure("Wanx credentials are unavailable")
        if not prompt.strip():
            raise WanxImageExplicitFailure("Wanx prompt is empty")
        content: list[dict[str, str]] = []
        if reference_image is not None:
            content.append({"image": self._reference_data_url(reference_image)})
        content.append({"text": prompt.strip()})
        parameters = {
            "size": "2K" if reference_image is not None else "1440*2560",
            "n": 1,
            "watermark": False,
        }
        if reference_image is None:
            parameters["thinking_mode"] = True
        payload = {
            "model": self.settings.wanx_image_model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ]
            },
            "parameters": parameters,
        }
        try:
            with httpx.Client(
                timeout=self.settings.wanx_image_timeout,
                transport=self.transport,
            ) as client:
                response = client.post(
                    self.settings.wanx_image_endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
        except httpx.ConnectError as exc:
            raise WanxImageExplicitFailure("Wanx connection failed") from exc
        except httpx.TimeoutException as exc:
            raise WanxImageSubmissionUnknown("Wanx result is unknown") from exc
        if response.status_code == 408 or response.status_code >= 500:
            raise WanxImageSubmissionUnknown("Wanx result is unknown")
        if response.is_error:
            raise WanxImageExplicitFailure("Wanx request failed")
        try:
            body = response.json()
            content = body["output"]["choices"][0]["message"]["content"]
            image_urls = [item["image"] for item in content if "image" in item]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise WanxImageExplicitFailure("Wanx response is invalid") from exc
        if len(image_urls) != 1 or not image_urls[0].startswith("https://"):
            raise WanxImageExplicitFailure("Wanx response is invalid")
        try:
            with httpx.Client(
                timeout=self.settings.wanx_image_timeout,
                transport=self.download_transport,
            ) as client:
                image_response = client.get(image_urls[0])
        except httpx.HTTPError as exc:
            raise WanxImageSubmissionUnknown("Wanx image delivery failed") from exc
        if image_response.is_error:
            raise WanxImageSubmissionUnknown("Wanx image delivery failed")
        image = image_response.content
        if not image or len(image) > self.settings.product_asset_max_bytes:
            raise WanxImageExplicitFailure("Wanx image size is invalid")
        request_id = body.get("request_id")
        request_digest = (
            hashlib.sha256(request_id.encode()).hexdigest()[:16]
            if isinstance(request_id, str) and request_id.strip()
            else None
        )
        return GeneratedWanxImage(image, request_digest)

    def _reference_data_url(self, content: bytes) -> str:
        if not content or len(content) > self.settings.product_asset_max_bytes:
            raise WanxImageExplicitFailure("Wanx reference image size is invalid")
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            media_type = "image/png"
        elif content.startswith(b"\xff\xd8\xff"):
            media_type = "image/jpeg"
        elif content.startswith(b"RIFF") and content[8:12] == b"WEBP":
            media_type = "image/webp"
        else:
            raise WanxImageExplicitFailure("Wanx reference image format is invalid")
        encoded = base64.b64encode(content).decode("ascii")
        return f"data:{media_type};base64,{encoded}"
