from __future__ import annotations

import hashlib
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Lock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import (
    get_optional_video_artifact_storage,
    get_text_generation_provider,
    get_video_artifact_storage,
    get_visual_generation_provider,
    get_youtube_provider,
)
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AdCampaign,
    CopyMatrix,
    DemoScenario,
    MarketingBrief,
    MarketingStrategy,
    PresentationSnapshot,
    Product,
    PublishTask,
    SocialAccount,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)
from app.repositories.presentation_snapshot import (
    PresentationSnapshotRepository,
)
from app.services.video_artifact_storage import LocalVideoArtifactStorage

ARTIFACT_CONTENT = b"fake-mp4-presentation-snapshot-content"


def snapshot_content_path(snapshot_id: int) -> str:
    return f"/api/v1/presentation-snapshots/{snapshot_id}/artifact/content"


def test_full_snapshot_is_provider_free_exact_and_idempotent(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    provider_resolutions = install_safe_dependencies(client, source["storage"])
    request = exact_request(source)
    before = source_counts(db_session)

    first = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=request,
    )
    second = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=request,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    snapshot = first_body["snapshot"]
    assert first_body["reused"] is False
    assert second_body["reused"] is True
    assert first_body["provider_calls"] == 0
    assert second_body["snapshot"]["id"] == snapshot["id"]
    assert second_body["snapshot"]["digest"] == snapshot["digest"]
    assert len(snapshot["digest"]) == 64
    assert snapshot["schema_version"] == 1
    assert snapshot["missing_sections"] == []
    assert snapshot["product_id"] == source["product"].id
    assert snapshot["marketing_brief_id"] == source["brief"].id
    assert snapshot["marketing_strategy_id"] == source["strategy"].id
    assert snapshot["copy_matrix_id"] == source["copy"].id
    assert snapshot["video_project_id"] == source["video"].id
    assert snapshot["render_task_id"] == source["render"].id
    assert snapshot["artifact_id"] == source["artifact"].id
    assert snapshot["publish_task_id"] == source["publish"].id
    assert snapshot["campaign_ids"] == [source["campaign"].id]
    assert snapshot["artifact_sha256"] == source["sha256"]
    assert snapshot["snapshot_payload"]["campaign_metrics"] == {
        "impressions": 1000,
        "clicks": 100,
        "conversions": 10,
        "spend": 50.0,
        "revenue": 200.0,
        "ctr": 0.1,
        "conversion_rate": 0.1,
        "cpa": 5.0,
        "roas": 4.0,
    }
    assert snapshot["snapshot_payload"]["publish_task"] == {
        "id": source["publish"].id,
        "product_id": source["product"].id,
        "social_account_id": source["account"].id,
        "artifact_id": source["artifact"].id,
        "platform": "youtube",
        "title": "Portable Blender",
        "description": "A private delivery record",
        "tags": ["portable"],
        "privacy_status": "private",
        "made_for_kids": False,
        "synthetic_media": True,
        "notify_subscribers": False,
        "status": "SUCCEEDED",
        "provider_video_id": "safe-video-id",
        "uncertain": False,
        "safe_error_code": None,
        "submitted_at": source["publish"].submitted_at.isoformat(),
        "completed_at": source["publish"].completed_at.isoformat(),
    }
    snapshot_path, content_type = source["storage"].resolve(
        snapshot["artifact_snapshot_path"]
    )
    assert snapshot_path != source["source_path"]
    assert snapshot_path.read_bytes() == ARTIFACT_CONTENT
    assert hashlib.sha256(snapshot_path.read_bytes()).hexdigest() == source["sha256"]
    assert content_type == "video/mp4"
    assert source_counts(db_session) == before
    assert db_session.scalar(select(func.count(PresentationSnapshot.id))) == 1
    assert db_session.scalar(select(func.count(DemoScenario.id))) == 0
    assert len(list(tmp_path.glob("*.mp4"))) == 2
    assert provider_resolutions == {
        "qwen": 0,
        "wanx": 0,
        "youtube": 0,
    }


def test_snapshot_artifact_content_is_exact_read_only_and_supports_ranges(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    provider_resolutions = install_safe_dependencies(client, source["storage"])
    app.dependency_overrides[get_video_artifact_storage] = lambda: source[
        "storage"
    ]
    created = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=exact_request(source),
    ).json()["snapshot"]
    snapshot_path, _ = source["storage"].resolve(
        created["artifact_snapshot_path"]
    )
    source["source_path"].write_bytes(b"changed-original-artifact")
    before = source_counts(db_session)
    snapshot_count = db_session.scalar(
        select(func.count(PresentationSnapshot.id))
    )

    full = client.get(snapshot_content_path(created["id"]))
    ranged = client.get(
        snapshot_content_path(created["id"]), headers={"Range": "bytes=5-12"}
    )
    head = client.head(snapshot_content_path(created["id"]))
    invalid_range = client.get(
        snapshot_content_path(created["id"]), headers={"Range": "bytes=999-"}
    )

    assert snapshot_path != source["source_path"]
    assert full.status_code == 200
    assert full.content == ARTIFACT_CONTENT
    assert full.headers["accept-ranges"] == "bytes"
    assert full.headers["content-length"] == str(len(ARTIFACT_CONTENT))
    assert full.headers["content-type"] == "video/mp4"
    assert ranged.status_code == 206
    assert ranged.content == ARTIFACT_CONTENT[5:13]
    assert ranged.headers["content-range"] == (
        f"bytes 5-12/{len(ARTIFACT_CONTENT)}"
    )
    assert head.status_code == 200
    assert head.content == b""
    assert invalid_range.status_code == 416
    assert invalid_range.headers["content-range"] == (
        f"bytes */{len(ARTIFACT_CONTENT)}"
    )
    assert source_counts(db_session) == before
    assert db_session.scalar(select(func.count(PresentationSnapshot.id))) == (
        snapshot_count
    )
    assert provider_resolutions == {"qwen": 0, "wanx": 0, "youtube": 0}


def test_snapshot_artifact_never_falls_back_and_verifies_snapshot_copy(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    provider_resolutions = install_safe_dependencies(client, source["storage"])
    app.dependency_overrides[get_video_artifact_storage] = lambda: source[
        "storage"
    ]
    created = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=exact_request(source),
    ).json()["snapshot"]
    snapshot_path, _ = source["storage"].resolve(
        created["artifact_snapshot_path"]
    )
    endpoint = snapshot_content_path(created["id"])

    snapshot_path.write_bytes(ARTIFACT_CONTENT + b"tampered")
    mismatch = client.get(endpoint)
    assert mismatch.status_code == 409
    assert str(tmp_path).casefold() not in mismatch.text.casefold()

    snapshot_path.unlink()
    missing = client.get(endpoint)
    assert missing.status_code == 404
    assert source["source_path"].is_file()
    assert client.get(snapshot_content_path(999_999)).status_code == 404
    assert provider_resolutions == {"qwen": 0, "wanx": 0, "youtube": 0}


def test_campaign_order_is_canonical_and_reuses_snapshot(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    install_safe_dependencies(client, source["storage"])
    second_campaign = AdCampaign(
        product_id=source["product"].id,
        platform="Instagram",
        campaign_name="Second Demo Campaign",
        date=date(2026, 8, 9),
        impressions=500,
        clicks=25,
        conversions=2,
        spend=Decimal("20.00"),
        revenue=Decimal("60.00"),
    )
    db_session.add(second_campaign)
    db_session.commit()
    canonical_ids = sorted([source["campaign"].id, second_campaign.id])
    reverse_request = exact_request(source)
    reverse_request["campaign_ids"] = list(reversed(canonical_ids))
    canonical_request = exact_request(source)
    canonical_request["campaign_ids"] = canonical_ids

    first = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=reverse_request,
    )
    second = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=canonical_request,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    first_snapshot = first.json()["snapshot"]
    second_snapshot = second.json()["snapshot"]
    assert first_snapshot["campaign_ids"] == canonical_ids
    assert first_snapshot["snapshot_payload"]["source_ids"]["campaign_ids"] == (
        canonical_ids
    )
    assert [
        campaign["id"]
        for campaign in first_snapshot["snapshot_payload"]["campaigns"]
    ] == canonical_ids
    assert second.json()["reused"] is True
    assert second_snapshot["id"] == first_snapshot["id"]
    assert second_snapshot["digest"] == first_snapshot["digest"]
    assert db_session.scalar(select(func.count(PresentationSnapshot.id))) == 1


def test_snapshot_deep_copy_survives_source_changes_and_rejects_update(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    install_safe_dependencies(client, source["storage"])
    request = exact_request(source)
    created = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=request,
    ).json()["snapshot"]
    original_payload = created["snapshot_payload"]

    source["product"].name = "Changed Product"
    source["product"].selling_points = ["Changed"]
    source["copy"].copies = copies("Changed")
    source["brief"].audience = "Changed Brief"
    source["campaign"].clicks = 1
    source["publish"].status = "FAILED"
    db_session.commit()
    app.dependency_overrides.pop(get_optional_video_artifact_storage)

    recovered = client.get(
        f"/api/v1/presentation-snapshots/{created['id']}"
    )
    assert recovered.status_code == 200
    assert recovered.json()["snapshot_payload"] == original_payload
    assert recovered.json()["snapshot_payload"]["product"]["name"] == (
        "Portable Blender"
    )
    assert original_payload["marketing_brief"] is not None
    assert recovered.json()["snapshot_payload"]["marketing_brief"] == (
        original_payload["marketing_brief"]
    )


    install_safe_dependencies(client, source["storage"])
    newer = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=request,
    )
    assert newer.status_code == 200
    assert newer.json()["snapshot"]["id"] != created["id"]
    assert newer.json()["snapshot"]["digest"] != created["digest"]

    record = db_session.get(PresentationSnapshot, created["id"])
    assert record is not None
    record.digest = "0" * 64
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()


def test_snapshot_payload_and_media_survive_source_record_deletion(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    provider_resolutions = install_safe_dependencies(client, source["storage"])
    app.dependency_overrides[get_video_artifact_storage] = lambda: source[
        "storage"
    ]
    created = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=exact_request(source),
    ).json()["snapshot"]
    frozen_payload = created["snapshot_payload"]

    for model in (
        PublishTask,
        SocialAccount,
        AdCampaign,
        VideoRenderArtifact,
        VideoRenderTask,
        VideoProject,
        CopyMatrix,
        MarketingBrief,
        MarketingStrategy,
        Product,
    ):
        db_session.execute(delete(model))
    db_session.commit()

    recovered = client.get(
        f"/api/v1/presentation-snapshots/{created['id']}"
    )
    media = client.get(snapshot_content_path(created["id"]))

    assert recovered.status_code == 200
    assert recovered.json()["snapshot_payload"] == frozen_payload
    assert recovered.json()["snapshot_payload"]["product"]["name"] == (
        "Portable Blender"
    )
    assert media.status_code == 200
    assert media.content == ARTIFACT_CONTENT
    assert db_session.get(PresentationSnapshot, created["id"]) is not None
    assert provider_resolutions == {"qwen": 0, "wanx": 0, "youtube": 0}
    assert recovered.json()["snapshot_payload"]["publish_task"]["status"] == (
        "SUCCEEDED"
    )
    assert recovered.json()["snapshot_payload"]["marketing_brief"]["audience"] == (
        frozen_payload["marketing_brief"]["audience"]
    )



def test_snapshot_delete_is_rejected_as_immutable(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    install_safe_dependencies(client, source["storage"])
    created = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=exact_request(source),
    ).json()["snapshot"]
    record = db_session.get(PresentationSnapshot, created["id"])
    assert record is not None

    db_session.delete(record)
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()

    assert db_session.get(PresentationSnapshot, created["id"]) is not None


def test_failed_database_commit_removes_new_artifact_copy(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    install_safe_dependencies(client, source["storage"])

    def fail_commit(
        repository: PresentationSnapshotRepository,
        snapshot: PresentationSnapshot,
    ) -> tuple[PresentationSnapshot, bool]:
        del repository, snapshot
        raise RuntimeError("forced database finalization failure")

    monkeypatch.setattr(
        PresentationSnapshotRepository,
        "create_or_reuse",
        fail_commit,
    )

    with pytest.raises(RuntimeError, match="finalization failure"):
        client.post(
            f"/api/v1/products/{source['product'].id}/presentation-snapshots",
            json=exact_request(source),
        )

    assert db_session.scalar(select(func.count(PresentationSnapshot.id))) == 0
    assert list(tmp_path.glob("*.mp4")) == [source["source_path"]]


def test_failed_loser_does_not_delete_winner_artifact(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    install_safe_dependencies(client, source["storage"])
    winner = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=exact_request(source),
    ).json()["snapshot"]
    winner_path = tmp_path / winner["artifact_snapshot_path"]
    assert winner_path.is_file()

    monkeypatch.setattr(
        PresentationSnapshotRepository,
        "get_by_digest",
        lambda repository, digest: None,
    )

    def fail_commit(
        repository: PresentationSnapshotRepository,
        snapshot: PresentationSnapshot,
    ) -> tuple[PresentationSnapshot, bool]:
        del repository, snapshot
        raise RuntimeError("forced losing database finalization failure")

    monkeypatch.setattr(
        PresentationSnapshotRepository,
        "create_or_reuse",
        fail_commit,
    )

    with pytest.raises(RuntimeError, match="losing database finalization"):
        client.post(
            f"/api/v1/products/{source['product'].id}/presentation-snapshots",
            json=exact_request(source),
        )

    assert winner_path.is_file()
    assert winner_path.read_bytes() == ARTIFACT_CONTENT
    assert db_session.scalar(select(func.count(PresentationSnapshot.id))) == 1


def test_missing_sections_remain_missing_and_never_use_latest(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    install_safe_dependencies(client, None)

    response = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json={"campaign_ids": []},
    )

    assert response.status_code == 200
    snapshot = response.json()["snapshot"]
    assert snapshot["marketing_brief_id"] is None
    assert snapshot["marketing_strategy_id"] is None
    assert snapshot["copy_matrix_id"] is None
    assert snapshot["video_project_id"] is None
    assert snapshot["render_task_id"] is None
    assert snapshot["artifact_id"] is None
    assert snapshot["publish_task_id"] is None
    assert snapshot["campaign_ids"] == []
    assert snapshot["missing_sections"] == [
        "marketing_brief",
        "marketing_strategy",
        "copy_matrix",
        "video_project",
        "render_task",
        "artifact",
        "publish_task",
        "campaigns",
    ]
    payload = snapshot["snapshot_payload"]
    assert payload["product"]["id"] == source["product"].id
    for section in snapshot["missing_sections"][:-1]:
        assert payload[section] is None
    assert payload["campaigns"] == []
    assert payload["campaign_metrics"] is None
    assert snapshot["artifact_sha256"] is None
    assert snapshot["artifact_snapshot_path"] is None
    assert len(list(tmp_path.glob("*.mp4"))) == 1



def test_brief_identity_rejects_missing_or_other_product_without_snapshot_write(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    install_safe_dependencies(client, source["storage"])
    other_product = Product(
        name="Other Product",
        category="Other Category",
        description="A separate product used for identity validation",
        selling_points=["Separate"],
        target_markets=["US"],
    )
    db_session.add(other_product)
    db_session.flush()
    other_brief = MarketingBrief(
        product_id=other_product.id,
        audience="Other audience",
        language="English",
        platforms=["TikTok"],
        tone="Clear",
        objective="Awareness",
    )
    db_session.add(other_brief)
    db_session.commit()

    wrong_product_request = exact_request(source)
    wrong_product_request["marketing_brief_id"] = other_brief.id
    wrong_product = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=wrong_product_request,
    )
    missing_request = exact_request(source)
    missing_request["marketing_brief_id"] = 999999
    missing = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=missing_request,
    )

    assert wrong_product.status_code == 409
    assert "MarketingBrief" in wrong_product.json()["error"]["message"]
    assert missing.status_code == 404
    assert missing.json()["error"]["message"] == "MarketingBrief not found"
    assert db_session.scalar(select(func.count(PresentationSnapshot.id))) == 0
    assert len(list(tmp_path.glob("*.mp4"))) == 1


def test_snapshot_contains_exact_selected_brief(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    install_safe_dependencies(client, source["storage"])
    response = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=exact_request(source),
    )

    assert response.status_code == 200
    snapshot = response.json()["snapshot"]
    assert snapshot["marketing_brief_id"] == source["brief"].id
    frozen_brief = snapshot["snapshot_payload"]["marketing_brief"]
    assert frozen_brief["id"] == source["brief"].id
    assert frozen_brief["audience"] == source["brief"].audience


def test_mismatched_exact_identity_is_rejected_without_snapshot_write(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    install_safe_dependencies(client, source["storage"])
    other_copy = CopyMatrix(
        product_id=source["product"].id,
        marketing_strategy_id=source["strategy"].id,
        copies=copies("Other"),
    )
    db_session.add(other_copy)
    db_session.commit()
    request = exact_request(source)
    request["copy_matrix_id"] = other_copy.id

    response = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=request,
    )

    assert response.status_code == 409
    assert "VideoProject" in response.json()["error"]["message"]
    assert db_session.scalar(select(func.count(PresentationSnapshot.id))) == 0
    assert len(list(tmp_path.glob("*.mp4"))) == 1


def test_actual_artifact_hash_mismatch_is_rejected(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    install_safe_dependencies(client, source["storage"])
    source["source_path"].write_bytes(b"x" * len(ARTIFACT_CONTENT))

    response = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=exact_request(source),
    )

    assert response.status_code == 409
    assert response.json()["error"]["message"] == (
        "Stable video artifact hash does not match metadata"
    )
    assert db_session.scalar(select(func.count(PresentationSnapshot.id))) == 0
    assert len(list(tmp_path.glob("*.mp4"))) == 1


def test_explicit_artifact_requires_local_storage_configuration(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    install_safe_dependencies(client, None)

    response = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=exact_request(source),
    )

    assert response.status_code == 503
    assert response.json()["error"]["message"] == (
        "Artifact storage is not configured"
    )
    assert db_session.scalar(select(func.count(PresentationSnapshot.id))) == 0


def test_snapshot_list_is_product_scoped(
    client: TestClient,
    db_session: Session,
    tmp_path: Path,
) -> None:
    source = seed_exact_chain(db_session, tmp_path)
    install_safe_dependencies(client, source["storage"])
    created = client.post(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots",
        json=exact_request(source),
    ).json()["snapshot"]

    response = client.get(
        f"/api/v1/products/{source['product'].id}/presentation-snapshots"
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [created["id"]]


def test_concurrent_requests_reuse_one_snapshot_and_artifact(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "concurrent-snapshots.db"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    with session_factory() as seed_session:
        source = seed_exact_chain(seed_session, artifact_root)
        request = exact_request(source)

    observed_session_ids: list[int] = []
    observed_session_ids_lock = Lock()

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as request_session:
            with observed_session_ids_lock:
                observed_session_ids.append(id(request_session))
            yield request_session

    app.dependency_overrides[get_db] = override_get_db
    concurrent_client = TestClient(app)
    provider_resolutions = install_safe_dependencies(
        concurrent_client, source["storage"]
    )
    barrier = Barrier(2)

    def submit() -> object:
        barrier.wait()
        return concurrent_client.post(
            f"/api/v1/products/{source['product'].id}/presentation-snapshots",
            json=request,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = [future.result() for future in [
                executor.submit(submit),
                executor.submit(submit),
            ]]
    finally:
        concurrent_client.close()
        app.dependency_overrides.clear()

    assert [response.status_code for response in responses] == [200, 200]
    bodies = [response.json() for response in responses]
    snapshots = [body["snapshot"] for body in bodies]
    assert {snapshot["id"] for snapshot in snapshots} == {snapshots[0]["id"]}
    assert {snapshot["digest"] for snapshot in snapshots} == {
        snapshots[0]["digest"]
    }
    assert {snapshot["artifact_snapshot_path"] for snapshot in snapshots} == {
        snapshots[0]["artifact_snapshot_path"]
    }
    assert sorted(body["reused"] for body in bodies) == [False, True]
    assert len(set(observed_session_ids)) == 2
    with session_factory() as verification_session:
        assert (
            verification_session.scalar(
                select(func.count(PresentationSnapshot.id))
            )
            == 1
        )
    snapshot_path = artifact_root / snapshots[0]["artifact_snapshot_path"]
    assert snapshot_path.is_file()
    assert snapshot_path.read_bytes() == ARTIFACT_CONTENT
    assert len(list(artifact_root.glob("*.mp4"))) == 2
    assert provider_resolutions == {"qwen": 0, "wanx": 0, "youtube": 0}
    engine.dispose()


def install_safe_dependencies(
    client: TestClient,
    storage: LocalVideoArtifactStorage | None,
) -> dict[str, int]:
    del client
    calls = {"qwen": 0, "wanx": 0, "youtube": 0}

    def forbidden(name: str):  # type: ignore[no-untyped-def]
        def fail():  # type: ignore[no-untyped-def]
            calls[name] += 1
            raise AssertionError(f"{name} Provider dependency was resolved")

        return fail

    app.dependency_overrides[get_optional_video_artifact_storage] = lambda: storage
    app.dependency_overrides[get_text_generation_provider] = forbidden("qwen")
    app.dependency_overrides[get_visual_generation_provider] = forbidden("wanx")
    app.dependency_overrides[get_youtube_provider] = forbidden("youtube")
    return calls


def exact_request(source: dict[str, object]) -> dict[str, object]:
    return {
        "marketing_brief_id": source["brief"].id,
        "marketing_strategy_id": source["strategy"].id,
        "copy_matrix_id": source["copy"].id,
        "video_project_id": source["video"].id,
        "render_task_id": source["render"].id,
        "artifact_id": source["artifact"].id,
        "publish_task_id": source["publish"].id,
        "campaign_ids": [source["campaign"].id],
    }


def seed_exact_chain(
    session: Session,
    root: Path,
) -> dict[str, object]:
    storage = LocalVideoArtifactStorage(root.resolve(), 10_000_000)
    stored = storage.store(
        task_id=1,
        content=ARTIFACT_CONTENT,
        content_type="video/mp4",
    )
    product = Product(
        name="Portable Blender",
        category="Appliance",
        description="Portable blender description",
        selling_points=["Portable", "Rechargeable"],
        target_markets=["US"],
    )
    session.add(product)
    session.flush()
    brief = MarketingBrief(
        product_id=product.id,
        audience="Busy professionals",
        language="English",
        platforms=["TikTok", "Instagram", "Facebook"],
        tone="Practical",
        objective="Conversion",
    )
    strategy = MarketingStrategy(
        product_id=product.id,
        positioning="Fresh drinks anywhere",
        audience_insights=["Portability matters"],
        angles=["Portable routine"],
        risks=["No health claims"],
        evidence=["USB rechargeable"],
    )
    session.add_all([brief, strategy])
    session.flush()
    copy_matrix = CopyMatrix(
        product_id=product.id,
        marketing_strategy_id=strategy.id,
        copies=copies("Fresh"),
    )
    session.add(copy_matrix)
    session.flush()
    video = VideoProject(
        product_id=product.id,
        marketing_strategy_id=strategy.id,
        copy_matrix_id=copy_matrix.id,
        platform="TikTok",
        title="Blend Anywhere",
        concept="Portable routine",
        duration_seconds=15,
        aspect_ratio="9:16",
        scenes=[
            {
                "sequence": 1,
                "duration_seconds": 15,
                "shot_type": "Product hero",
                "visual_description": "Blender on a desk",
                "action": "Blend and go",
                "narration": "Fresh drinks anywhere",
            }
        ],
        cta="Shop now",
        status="planned",
    )
    session.add(video)
    session.flush()
    render = VideoRenderTask(
        video_project_id=video.id,
        scene_sequence=1,
        status="SUCCEEDED",
        provider_name="fake-wanx",
        provider_task_id="fake-task",
        render_prompt="Safe fake prompt",
        duration_seconds=15,
        aspect_ratio="9:16",
        resolution="720P",
        idempotency_key="fake-render-key",
    )
    session.add(render)
    session.flush()
    artifact = VideoRenderArtifact(
        video_render_task_id=render.id,
        storage_path=stored.relative_path,
        artifact_metadata={
            "content_type": stored.content_type,
            "size_bytes": stored.size_bytes,
            "sha256": stored.sha256,
            "scene_sequence": 1,
        },
    )
    session.add(artifact)
    session.flush()
    account = SocialAccount(
        product_id=product.id,
        platform="youtube",
        provider_account_id="safe-channel-id",
        display_name="Safe Channel",
        scopes=["youtube.upload"],
        access_token_ciphertext="encrypted-access",
        refresh_token_ciphertext="encrypted-refresh",
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        connection_status="CONNECTED",
        encryption_key_id="test",
    )
    session.add(account)
    session.flush()
    now = datetime.now(UTC)
    publish = PublishTask(
        product_id=product.id,
        social_account_id=account.id,
        artifact_id=artifact.id,
        platform="youtube",
        idempotency_key="fake-publish-key",
        request_digest="1" * 64,
        preflight_digest="2" * 64,
        title="Portable Blender",
        description="A private delivery record",
        tags=["portable"],
        privacy_status="private",
        made_for_kids=False,
        synthetic_media=True,
        notify_subscribers=False,
        status="SUCCEEDED",
        provider_video_id="safe-video-id",
        uncertain=False,
        submitted_at=now,
        completed_at=now,
    )
    campaign = AdCampaign(
        product_id=product.id,
        platform="TikTok",
        campaign_name="Demo Campaign",
        date=date(2026, 8, 8),
        impressions=1000,
        clicks=100,
        conversions=10,
        spend=Decimal("50.00"),
        revenue=Decimal("200.00"),
    )
    session.add_all([publish, campaign])
    session.commit()
    return {
        "storage": storage,
        "source_path": root / stored.relative_path,
        "sha256": stored.sha256,
        "product": product,
        "brief": brief,
        "strategy": strategy,
        "copy": copy_matrix,
        "video": video,
        "render": render,
        "artifact": artifact,
        "account": account,
        "publish": publish,
        "campaign": campaign,
    }


def copies(prefix: str) -> list[dict[str, object]]:
    return [
        {
            "platform": platform,
            "hook": f"{prefix} {platform} hook",
            "caption": f"{prefix} {platform} caption",
            "hashtags": ["#Portable"],
            "cta": "Shop now",
        }
        for platform in ("TikTok", "Instagram", "Facebook")
    ]


def source_counts(session: Session) -> dict[str, int]:
    return {
        model.__tablename__: session.scalar(select(func.count(model.id))) or 0
        for model in (
            Product,
            MarketingBrief,
            MarketingStrategy,
            CopyMatrix,
            VideoProject,
            VideoRenderTask,
            VideoRenderArtifact,
            SocialAccount,
            PublishTask,
            AdCampaign,
        )
    }
