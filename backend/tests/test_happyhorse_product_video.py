import asyncio
import hashlib
import struct
import subprocess
import zlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.orm import Session, sessionmaker

import app.services.happyhorse_product_video_service as happyhorse_service_module
from app.core.config import Settings
from app.core.exceptions import AppError
from app.execution.handlers.happyhorse_product_video import (
    HappyHorseProductVideoRefreshV1Handler,
    HappyHorseProductVideoSubmitV1Handler,
)
from app.execution.registry import ExecutionHandlerRegistry
from app.execution.worker import ExecutionWorker, WorkerRunStatus
from app.models import (
    ExecutionJob,
    Product,
    ProductAsset,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
    VideoScriptVersion,
    VideoStoryboardSceneVersion,
)
from app.providers.happyhorse_provider import HappyHorseProvider
from app.providers.visual_base import (
    VisualGenerationProvider,
    VisualGenerationRequest,
    VisualReferenceImage,
    VisualTaskSnapshot,
    VisualTaskSubmission,
)
from app.schemas.product_marketing_video import (
    HappyHorseReferenceImage,
    HappyHorseVideoPreflightRequest,
    HappyHorseVideoRefreshRequest,
    HappyHorseVideoSubmitRequest,
    WanxProductImageSubmitRequest,
)
from app.services.happyhorse_product_video_service import (
    HappyHorseProductVideoService,
)
from app.services.happyhorse_reference_media import (
    HAPPYHORSE_REFERENCE_MAX_BYTES,
    HAPPYHORSE_REFERENCE_MEDIA_CONTRACT,
    HappyHorseReferenceMedia,
)
from app.services.video_artifact_storage import LocalVideoArtifactStorage
from app.services.wanx_product_image_service import WanxProductImageService
from tests.test_video_render_execution_service import FakeOutputFetcher


class FakeHappyHorse(VisualGenerationProvider):
    def __init__(self) -> None:
        self.submit_calls = 0
        self.fetch_calls = 0
        self.reference_count = 0
        self.references: tuple[VisualReferenceImage, ...] = ()

    async def submit(self, request: VisualGenerationRequest) -> VisualTaskSubmission:
        self.submit_calls += 1
        self.reference_count = len(request.reference_images)
        self.references = request.reference_images
        return VisualTaskSubmission("happyhorse-task-1", None, "PENDING")

    async def fetch(self, provider_task_id: str) -> VisualTaskSnapshot:
        self.fetch_calls += 1
        return VisualTaskSnapshot(
            provider_task_id=provider_task_id,
            status="SUCCEEDED",
            provider_output_url="https://provider.example/video.mp4",
        )


def png_bytes(width: int = 1080, height: int = 1920) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    row = b"\x00" + b"\x15\x2d\x50" * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height, 9))
        + chunk(b"IEND", b"")
    )


def test_happyhorse_reference_media_is_bounded_720p_jpeg(tmp_path: Path) -> None:
    reference = HappyHorseReferenceMedia("ffmpeg", 60).normalize(
        png_bytes(1440, 2560), "image/png"
    )

    assert reference.content_type == "image/jpeg"
    assert reference.content.startswith(b"\xff\xd8\xff")
    assert len(reference.content) <= HAPPYHORSE_REFERENCE_MAX_BYTES
    path = tmp_path / "reference.jpg"
    path.write_bytes(reference.content)
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(path),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert probe.returncode == 0
    assert probe.stdout.strip() == "720x1280"


def test_wanx_prompt_replaces_visual_ui_instructions_with_generic_hero_shot() -> None:
    prompt = WanxProductImageService._prompt(
        SimpleNamespace(
            name="Reference Product",
            category="Consumer product",
            selling_points=["Portable", "Durable"],
        ),
        SimpleNamespace(concept="Show the real product benefit"),
        SimpleNamespace(
            visual_description="Product beside a buy button overlay graphic",
            action_description="Presenter gestures to the product and link below",
        ),
    )

    assert "buy button" not in prompt.casefold()
    assert "link below" not in prompt.casefold()
    assert "clean full-product hero shot" in prompt
    assert "natural presentation gesture" in prompt
    assert "Reference Product" in prompt


def test_wanx_job_freezes_and_resolves_exact_product_reference(
    db_session: Session, tmp_path: Path
) -> None:
    product = Product(
        name="Reference Blender",
        category="Portable appliance",
        description="A fictional portable blender for a controlled demo.",
        selling_points=["Portable", "Rechargeable", "Easy cleaning"],
        target_markets=["US"],
    )
    db_session.add(product)
    db_session.flush()
    content = b"\x89PNG\r\n\x1a\nreference-product"
    digest = hashlib.sha256(content).hexdigest()
    identity = f"product-images/{digest[:2]}/{digest}.png"
    asset = ProductAsset(
        product_id=product.id,
        file_name="reference.png",
        file_path=identity,
        file_type="png",
        content_type="image/png",
        size_bytes=len(content),
        sha256=digest,
        width=1440,
        height=2560,
        storage_identity=identity,
    )
    version = VideoScriptVersion(
        batch_video_variant_id=1,
        version_number=1,
        source_type="QWEN_GENERATED",
        source_digest="a" * 64,
        content_digest="b" * 64,
        idempotency_key="wanx-reference-version",
        product_id=product.id,
        product_content_digest="c" * 64,
        platform="youtube",
        language="en-US",
        title="Reference product demo",
        concept="Show the exact reference product in action",
        hook="Blend anywhere",
        full_narration="Blend anywhere with portable power.",
        cta="Shop now",
        full_subtitle_draft="Blend anywhere with portable power.",
        created_by_kind="QWEN_PROVIDER",
        review_status="UNREVIEWED",
    )
    version.scenes = [
        VideoStoryboardSceneVersion(
            sequence=1,
            start_ms=0,
            end_ms=3000,
            shot_type="close",
            visual_description="Show active blending",
            action_description="Press the button and blend fruit",
            narration="Blend anywhere with portable power.",
            subtitle_draft="Blend anywhere with portable power.",
        )
    ]
    db_session.add_all([asset, version])
    db_session.commit()
    image_path = tmp_path / "images" / identity
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(content)
    settings = Settings(
        qwen_api_key="fake-token-plan-key",
        enable_real_product_video=True,
        product_asset_storage_root=str(tmp_path / "images"),
    )
    service = WanxProductImageService(db_session, settings)
    request = WanxProductImageSubmitRequest(
        script_version_id=version.id,
        scene_sequence=1,
        reference_product_asset_id=asset.id,
        reference_product_asset_sha256=digest,
        idempotency_key="wanx-reference-job",
        cost_confirmed=True,
    )
    submitted = service.enqueue(product.id, request)
    assert submitted.reused is False
    assert submitted.job.input_payload["reference_product_asset_id"] == asset.id
    assert submitted.job.input_payload["reference_product_asset_sha256"] == digest
    assert "authoritative product identity" in submitted.job.input_payload["prompt"]
    assert "Add zero new written characters" in submitted.job.input_payload["prompt"]
    assert (
        "Never add, move, or redesign buttons, ports, cables"
        in (submitted.job.input_payload["prompt"])
    )
    assert (
        "category-appropriate visible state changes, natural product usage"
        in (submitted.job.input_payload["prompt"])
    )
    assert (
        "Never assume food, liquid, electronics"
        in submitted.job.input_payload["prompt"]
    )
    assert (
        "Preserve packaging, labels, and brand marks"
        in submitted.job.input_payload["prompt"]
    )
    assert service.reference_content(product.id, asset.id, digest) == content
    with pytest.raises(AppError, match="reference product asset"):
        service.enqueue(
            product.id,
            request.model_copy(update={"reference_product_asset_sha256": "d" * 64}),
        )
    assert db_session.query(ExecutionJob).count() == 1


def test_happyhorse_provider_submits_exact_r2v_contract_without_leaking_key() -> None:
    calls = {"submit": 0, "refresh": 0}

    def transport(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer fake-token-plan-key"
        if request.method == "POST":
            calls["submit"] += 1
            payload = __import__("json").loads(request.content)
            assert payload["model"] == "happyhorse-1.1-r2v"
            assert payload["parameters"] == {
                "duration": 15,
                "ratio": "9:16",
                "resolution": "720P",
            }
            assert payload["input"]["media"] == [
                {
                    "type": "reference_image",
                    "url": "data:image/png;base64,aW1hZ2U=",
                }
            ]
            return httpx.Response(
                200,
                json={
                    "output": {"task_id": "task-1", "task_status": "PENDING"},
                    "request_id": "request-1",
                },
            )
        calls["refresh"] += 1
        return httpx.Response(
            200,
            json={
                "output": {
                    "task_id": "task-1",
                    "task_status": "SUCCEEDED",
                    "video_url": "https://example.invalid/video.mp4",
                }
            },
        )

    provider = HappyHorseProvider(
        Settings(qwen_api_key="fake-token-plan-key"),
        transport=httpx.MockTransport(transport),
    )
    submitted = asyncio.run(
        provider.submit(
            VisualGenerationRequest(
                prompt="Premium product video",
                duration_seconds=15,
                aspect_ratio="9:16",
                resolution="720P",
                reference_images=(VisualReferenceImage(b"image", "image/png"),),
            )
        )
    )
    refreshed = asyncio.run(provider.fetch(submitted.provider_task_id))
    assert submitted.provider_task_id == "task-1"
    assert refreshed.status == "SUCCEEDED"
    assert calls == {"submit": 1, "refresh": 1}


def test_happyhorse_preflight_and_enqueue_freeze_exact_reference_images(
    db_session: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    product = Product(
        name="Fictional Product",
        category="Demo",
        description="A sufficiently detailed fictional product description.",
        selling_points=["Portable"],
        target_markets=["US"],
    )
    db_session.add(product)
    db_session.flush()
    content = b"image"
    digest = hashlib.sha256(content).hexdigest()
    identity = f"product-images/{digest[:2]}/{digest}.png"
    asset = ProductAsset(
        product_id=product.id,
        file_name="reference.png",
        file_path=identity,
        file_type="png",
        content_type="image/png",
        size_bytes=len(content),
        sha256=digest,
        width=1024,
        height=1024,
        storage_identity=identity,
    )
    project = VideoProject(
        product_id=product.id,
        marketing_strategy_id=1,
        copy_matrix_id=1,
        platform="TikTok",
        title="Product launch",
        concept="Premium portable product",
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[
            {
                "sequence": 1,
                "visual_description": "Hero shot",
                "action": "Slow orbit",
            }
        ],
        cta="Shop now",
        source_script_version_id=7,
        source_script_content_digest="a" * 64,
    )
    db_session.add_all([asset, project])
    db_session.commit()
    settings = Settings(
        qwen_api_key="fake-token-plan-key",
        enable_happyhorse_product_video=True,
        product_asset_storage_root=str(tmp_path / "images"),
        video_artifact_storage_root=str(tmp_path / "videos"),
    )
    request = HappyHorseVideoPreflightRequest(
        video_project_id=project.id,
        script_version_id=7,
        reference_images=[
            HappyHorseReferenceImage(
                product_asset_id=asset.id,
                product_asset_sha256=digest,
            )
        ],
    )
    service = HappyHorseProductVideoService(db_session, settings)
    prompt = service._prompt(project)
    assert "Visibly demonstrate the scripted product operation and benefits" in prompt
    assert "rather than showing only a static rotating hero shot" in prompt
    assert "supported by its category, script, and reference images" in prompt
    assert "Never expose hazardous internals" in prompt
    assert "Preserve existing product identity marks" in prompt
    checked = service.preflight(product.id, request)
    assert checked.ready is True
    with monkeypatch.context() as scoped:
        scoped.setattr(
            happyhorse_service_module,
            "HAPPYHORSE_REFERENCE_MEDIA_CONTRACT",
            f"{HAPPYHORSE_REFERENCE_MEDIA_CONTRACT}-changed",
        )
        changed_contract = service.preflight(
            product.id, request, expires_at=checked.expires_at
        )
    assert changed_contract.input_digest != checked.input_digest
    submit = HappyHorseVideoSubmitRequest(
        **request.model_dump(),
        input_digest=checked.input_digest,
        preflight_digest=checked.preflight_digest,
        preflight_expires_at=checked.expires_at,
        cost_confirmed=True,
    )
    first = service.enqueue_submit(product.id, submit)
    second = service.enqueue_submit(product.id, submit)
    assert first.reused is False and second.reused is True
    assert first.job.id == second.job.id
    assert first.job.job_type == "happyhorse.product_video.submit.v1"
    assert first.job.max_attempts == 1
    assert first.job.estimated_cost == settings.happyhorse_estimated_cost
    assert db_session.query(ExecutionJob).count() == 1


def test_happyhorse_worker_submits_once_and_refresh_persists_artifact(
    db_session: Session, tmp_path: Path
) -> None:
    product = Product(
        name="Worker Product",
        category="Demo",
        description="A sufficiently detailed fictional product description.",
        selling_points=["Portable"],
        target_markets=["US"],
    )
    db_session.add(product)
    db_session.flush()
    content = png_bytes()
    digest = hashlib.sha256(content).hexdigest()
    identity = f"product-images/{digest[:2]}/{digest}.png"
    asset = ProductAsset(
        product_id=product.id,
        file_name="reference.png",
        file_path=identity,
        file_type="png",
        content_type="image/png",
        size_bytes=len(content),
        sha256=digest,
        width=1024,
        height=1024,
        storage_identity=identity,
    )
    project = VideoProject(
        product_id=product.id,
        marketing_strategy_id=1,
        copy_matrix_id=1,
        platform="TikTok",
        title="Worker launch",
        concept="Premium portable product",
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[
            {
                "sequence": 1,
                "visual_description": "Hero shot",
                "action": "Slow orbit",
            }
        ],
        cta="Shop now",
        source_script_version_id=8,
        source_script_content_digest="b" * 64,
    )
    db_session.add_all([asset, project])
    db_session.commit()
    image_path = tmp_path / "images" / identity
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(content)
    settings = Settings(
        qwen_api_key="fake-token-plan-key",
        enable_happyhorse_product_video=True,
        enable_video_render_execution=True,
        product_asset_storage_root=str(tmp_path / "images"),
        video_artifact_storage_root=str(tmp_path / "videos"),
    )
    request = HappyHorseVideoPreflightRequest(
        video_project_id=project.id,
        script_version_id=8,
        reference_images=[
            HappyHorseReferenceImage(
                product_asset_id=asset.id,
                product_asset_sha256=digest,
            )
        ],
    )
    service = HappyHorseProductVideoService(db_session, settings)
    checked = service.preflight(product.id, request)
    submitted = service.enqueue_submit(
        product.id,
        HappyHorseVideoSubmitRequest(
            **request.model_dump(),
            input_digest=checked.input_digest,
            preflight_digest=checked.preflight_digest,
            preflight_expires_at=checked.expires_at,
            cost_confirmed=True,
        ),
    )
    sessions = sessionmaker(bind=db_session.bind, expire_on_commit=False)
    provider = FakeHappyHorse()
    fetcher = FakeOutputFetcher(content=b"fake-happyhorse-video")
    storage = LocalVideoArtifactStorage(tmp_path / "videos", 1_000_000)
    registry = ExecutionHandlerRegistry()
    registry.register(
        HappyHorseProductVideoSubmitV1Handler(
            session_factory=sessions,
            provider=provider,
            settings=settings,
            output_fetcher=fetcher,
            artifact_storage=storage,
        )
    )
    registry.register(
        HappyHorseProductVideoRefreshV1Handler(
            session_factory=sessions,
            provider=provider,
            settings=settings,
            output_fetcher=fetcher,
            artifact_storage=storage,
        )
    )
    worker = ExecutionWorker(
        session_factory=sessions,
        registry=registry,
        worker_id="happyhorse-worker",
        heartbeat_interval_seconds=5,
    )
    worker_result = worker.run_once()
    db_session.expire_all()
    worker_job = db_session.get(ExecutionJob, submitted.job.id)
    assert worker_job is not None
    assert worker_result.status == WorkerRunStatus.SUCCEEDED, worker_job.safe_error_code
    db_session.expire_all()
    submit_job = db_session.get(ExecutionJob, submitted.job.id)
    assert submit_job is not None
    task = db_session.get(VideoRenderTask, submit_job.result_entity_id)
    assert task is not None and task.provider_name == "happyhorse"
    assert provider.submit_calls == 1 and provider.reference_count == 1
    assert provider.references[0].content_type == "image/jpeg"
    assert provider.references[0].content.startswith(b"\xff\xd8\xff")
    assert len(provider.references[0].content) <= HAPPYHORSE_REFERENCE_MAX_BYTES
    refresh = service.enqueue_refresh(
        product.id,
        task.id,
        HappyHorseVideoRefreshRequest(
            video_project_id=project.id,
            refresh_request_id="refresh-request-0001",
        ),
    )
    assert worker.run_once().status == WorkerRunStatus.SUCCEEDED
    db_session.expire_all()
    refresh_job = db_session.get(ExecutionJob, refresh.job.id)
    artifact = db_session.get(VideoRenderArtifact, refresh_job.result_entity_id)
    assert artifact is not None
    assert provider.fetch_calls == 1 and fetcher.calls == 1
