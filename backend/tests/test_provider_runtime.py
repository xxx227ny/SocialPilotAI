import pytest

from app.core.provider_runtime import resolve_workspace_provider_runtime


def test_default_profile_uses_global_beijing_endpoints() -> None:
    runtime = resolve_workspace_provider_runtime(
        api_key="sk-user-key",
        region="cn-beijing",
        provider_workspace_id=None,
    )

    assert runtime.qwen_endpoint == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    assert runtime.native_endpoint == "https://dashscope.aliyuncs.com/api/v1"
    assert runtime.models_endpoint == "https://dashscope.aliyuncs.com/api/v1/models"
    assert runtime.wanx_image_endpoint == (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/"
        "multimodal-generation/generation"
    )


def test_workspace_profile_builds_only_allowlisted_provider_hosts() -> None:
    runtime = resolve_workspace_provider_runtime(
        api_key="sk-user-key",
        region="CN-BEIJING",
        provider_workspace_id=" Workspace-ABC-9 ",
    )

    assert runtime.region == "cn-beijing"
    assert runtime.provider_workspace_id == "workspace-abc-9"
    assert runtime.qwen_endpoint == (
        "https://workspace-abc-9.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    assert runtime.native_endpoint == (
        "https://workspace-abc-9.cn-beijing.maas.aliyuncs.com/api/v1"
    )


def test_workspace_profile_accepts_full_beijing_workspace_hostname() -> None:
    runtime = resolve_workspace_provider_runtime(
        api_key="sk-user-key",
        region="cn-beijing",
        provider_workspace_id=(
            "WS-Example-9.cn-beijing.maas.aliyuncs.com"
        ),
    )

    assert runtime.provider_workspace_id == "ws-example-9"
    assert runtime.native_endpoint == (
        "https://ws-example-9.cn-beijing.maas.aliyuncs.com/api/v1"
    )


@pytest.mark.parametrize(
    "workspace_id",
    [
        "https://attacker.invalid/path",
        "workspace.example.com",
        "../workspace",
        "-starts-with-hyphen",
        "ends-with-hyphen-",
        "a" * 64,
    ],
)
def test_workspace_profile_rejects_arbitrary_hosts_and_paths(
    workspace_id: str,
) -> None:
    with pytest.raises(ValueError, match="workspace ID"):
        resolve_workspace_provider_runtime(
            api_key="sk-user-key",
            region="cn-beijing",
            provider_workspace_id=workspace_id,
        )


def test_workspace_profile_rejects_unsupported_region() -> None:
    with pytest.raises(ValueError, match="region"):
        resolve_workspace_provider_runtime(
            api_key="sk-user-key",
            region="cn-shanghai",
            provider_workspace_id=None,
        )
