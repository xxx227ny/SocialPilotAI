from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_PROVIDER_REGION = "cn-beijing"
SUPPORTED_PROVIDER_REGIONS = frozenset({DEFAULT_PROVIDER_REGION})
_WORKSPACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


@dataclass(frozen=True, slots=True)
class WorkspaceProviderRuntime:
    api_key: str
    region: str
    provider_workspace_id: str | None
    qwen_endpoint: str
    native_endpoint: str

    @property
    def models_endpoint(self) -> str:
        return f"{self.native_endpoint}/models"

    @property
    def wanx_image_endpoint(self) -> str:
        return f"{self.native_endpoint}/services/aigc/multimodal-generation/generation"

    @property
    def qwen_tts_endpoint(self) -> str:
        return f"{self.native_endpoint}/services/audio/tts/SpeechSynthesizer"

    @property
    def happyhorse_endpoint(self) -> str:
        return self.native_endpoint


def resolve_workspace_provider_runtime(
    *,
    api_key: str,
    region: str,
    provider_workspace_id: str | None,
) -> WorkspaceProviderRuntime:
    normalized_region = region.strip().lower()
    if normalized_region not in SUPPORTED_PROVIDER_REGIONS:
        raise ValueError("Provider region is not supported")
    normalized_workspace_id = _normalize_workspace_id(provider_workspace_id)
    host = (
        f"{normalized_workspace_id}.cn-beijing.maas.aliyuncs.com"
        if normalized_workspace_id
        else "dashscope.aliyuncs.com"
    )
    return WorkspaceProviderRuntime(
        api_key=api_key,
        region=normalized_region,
        provider_workspace_id=normalized_workspace_id,
        qwen_endpoint=f"https://{host}/compatible-mode/v1",
        native_endpoint=f"https://{host}/api/v1",
    )


def _normalize_workspace_id(value: str | None) -> str | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    if not _WORKSPACE_ID_PATTERN.fullmatch(normalized):
        raise ValueError("Provider workspace ID is invalid")
    return normalized.lower()
