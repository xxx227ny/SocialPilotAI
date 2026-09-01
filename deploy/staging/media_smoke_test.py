"""Seed one non-billable artifact and verify deployed preview delivery."""

import argparse
import hashlib
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import (
    MarketingStrategy,
    Product,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.services.video_artifact_storage import LocalVideoArtifactStorage
from app.services.video_preview import PREVIEW_VERSION


def require_status(response: httpx.Response, expected: int) -> None:
    if response.status_code != expected:
        raise RuntimeError(
            f"{response.request.method} {response.request.url.path} returned "
            f"{response.status_code}, expected {expected}"
        )


def register(client: httpx.Client, run_id: str, suffix: str) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"media-{suffix}-{run_id}@invalid.example",
            "password": "Media-" + secrets.token_urlsafe(20),
            "workspace_name": f"Media Validation {suffix.upper()}",
        },
    )
    require_status(response, 201)
    return response.json()


def seed_artifact(
    database: Path,
    artifact_root: Path,
    fixture: Path,
    workspace_id: int,
    run_id: str,
) -> tuple[int, str]:
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    content = fixture.read_bytes()
    with Session(engine) as session:
        product = Product(
            workspace_id=workspace_id,
            name=f"Media Validation Product {run_id}",
            category="Deployment Validation",
            description="A non-billable product for deployed media validation.",
            selling_points=["Fast authenticated preview"],
            target_markets=["Validation only"],
        )
        session.add(product)
        session.flush()
        strategy = MarketingStrategy(
            product_id=product.id,
            positioning="Validate private media delivery.",
            audience_insights=["Internal staging validation."],
            angles=["Fast preview."],
            risks=["Never publish this fixture."],
            evidence=["Verified local MP4 fixture."],
        )
        session.add(strategy)
        session.flush()
        project = VideoProject(
            product_id=product.id,
            marketing_strategy_id=strategy.id,
            copy_matrix_id=None,
            platform="TikTok",
            title="Media delivery validation",
            concept="Validate range delivery without provider calls.",
            duration_seconds=3,
            aspect_ratio="9:16",
            scenes=[
                {
                    "sequence": 1,
                    "duration_seconds": 3,
                    "shot_type": "Validation",
                    "visual_description": "Verified staging fixture.",
                    "action": "No external action.",
                    "narration": "Validation only.",
                }
            ],
            cta="None",
            status="completed",
            source_input_digest=hashlib.sha256(run_id.encode()).hexdigest(),
        )
        session.add(project)
        session.flush()
        task = VideoRenderTask(
            video_project_id=project.id,
            scene_sequence=1,
            status="SUCCEEDED",
            provider_name="staging-validation",
            provider_task_id=None,
            render_prompt="Non-billable staging fixture.",
            duration_seconds=3,
            aspect_ratio="9:16",
            resolution="720P",
            idempotency_key=f"media-smoke-{run_id}",
            error_code=None,
            error_message=None,
        )
        session.add(task)
        session.flush()
        stored, _ = LocalVideoArtifactStorage(
            artifact_root.resolve(), 500_000_000
        ).store_immutable(
            task_id=task.id,
            content=content,
            content_type="video/mp4",
        )
        artifact = VideoRenderArtifact(
            video_render_task_id=task.id,
            provider_output_url=None,
            storage_path=stored.relative_path,
            artifact_metadata={
                "content_type": stored.content_type,
                "size_bytes": stored.size_bytes,
                "sha256": stored.sha256,
            },
        )
        session.add(artifact)
        session.commit()
        session.refresh(artifact)
        return artifact.id, stored.sha256


def timed_range(client: httpx.Client, path: str) -> tuple[httpx.Response, float]:
    started = perf_counter()
    response = client.get(path, headers={"Range": "bytes=0-1023"})
    return response, perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    arguments = parser.parse_args()
    origin = arguments.origin.rstrip("/")
    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S") + secrets.token_hex(3)
    headers = {"Origin": origin}

    with (
        httpx.Client(
            base_url=origin, headers=headers, timeout=180, trust_env=False
        ) as owner,
        httpx.Client(
            base_url=origin, headers=headers, timeout=30, trust_env=False
        ) as other,
    ):
        owner_account = register(owner, run_id, "owner")
        register(other, run_id, "other")
        artifact_id, digest = seed_artifact(
            arguments.database,
            arguments.artifact_root,
            arguments.fixture,
            int(owner_account["workspace_id"]),
            run_id,
        )
        preview_path = f"/api/v1/video-render-artifacts/{artifact_id}/preview"
        source_path = f"/api/v1/video-render-artifacts/{artifact_id}/content"

        first, first_seconds = timed_range(owner, preview_path)
        second, cached_seconds = timed_range(owner, preview_path)
        source, source_seconds = timed_range(owner, source_path)
        for response in (first, second, source):
            require_status(response, 206)
            if len(response.content) != 1024:
                raise RuntimeError("Range response returned an unexpected length")
            if response.headers.get("accept-ranges") != "bytes":
                raise RuntimeError("Range support header is missing")
        if first.headers.get("cdn-cache-control") != "no-store":
            raise RuntimeError("Private media could be cached by a shared CDN")
        if "private" not in first.headers.get("cache-control", ""):
            raise RuntimeError("Private browser cache policy is missing")
        require_status(other.get(preview_path), 404)

    generated = (
        arguments.artifact_root
        / ".previews"
        / f"{digest}-{PREVIEW_VERSION}.mp4"
    )
    preview_bytes = generated.read_bytes()
    moov = preview_bytes.find(b"moov")
    mdat = preview_bytes.find(b"mdat")
    if moov < 0 or mdat < 0 or moov > mdat:
        raise RuntimeError("Preview MP4 is not optimized for fast start")
    metrics = {
        "cached_preview_seconds": round(cached_seconds, 3),
        "first_preview_seconds": round(first_seconds, 3),
        "preview_bytes": generated.stat().st_size,
        "source_bytes": arguments.fixture.stat().st_size,
        "source_range_seconds": round(source_seconds, 3),
    }
    print(json.dumps(metrics, sort_keys=True))
    print("Deployed media smoke passed: range, fast-start, cache, and isolation")


if __name__ == "__main__":
    main()
