import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings, get_settings
from app.main import app
from app.models import ProductAsset
from app.services import product_thumbnail
from app.services.demo_auth_service import hash_password
from tests.test_products import create_product, png_bytes


@pytest.fixture
def preview_asset(client, db_session, tmp_path, product_payload):
    product = create_product(client, product_payload)
    content = png_bytes(1024, 768)
    digest = hashlib.sha256(content).hexdigest()
    path = tmp_path / "original.png"
    path.write_bytes(content)
    asset = ProductAsset(
        product_id=product["id"],
        file_name="original.png",
        file_path="original.png",
        file_type="png",
        content_type="image/png",
        size_bytes=len(content),
        sha256=digest,
        width=1024,
        height=768,
        storage_identity="original.png",
    )
    db_session.add(asset)
    db_session.commit()
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, product_asset_storage_root=str(tmp_path)
    )
    return product["id"], asset.id, path, digest


def test_thumbnail_private_revalidation_and_ownership(
    client, db_session, preview_asset, monkeypatch
):
    product_id, asset_id, original, digest = preview_asset
    encoded = []

    def fake_encoder(command, **kwargs):
        encoded.append(command)
        Path(command[-1]).write_bytes(b"RIFF-preview-WEBP")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(product_thumbnail.subprocess, "run", fake_encoder)
    url = f"/api/v1/products/{product_id}/image-assets/{asset_id}/thumbnail"
    first = client.get(url)
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/webp"
    assert first.headers["cache-control"] == "private, no-cache"
    assert first.headers["vary"] == "Cookie"
    assert client.head(url).status_code == 200
    assert len(encoded) == 1
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    headers = {"If-None-Match": first.headers["etag"]}
    assert client.get(url, headers=headers).status_code == 304
    assert (
        client.get(
            url.replace(f"products/{product_id}/", "products/999/"), headers=headers
        ).status_code
        == 404
    )
    db_session.delete(db_session.get(ProductAsset, asset_id))
    db_session.commit()
    assert client.get(url, headers=headers).status_code == 404


def test_thumbnail_auth_required_even_with_etag(client, preview_asset):
    product_id, asset_id, original, _ = preview_asset
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        product_asset_storage_root=str(original.parent),
        enable_demo_auth=True,
        demo_auth_username="preview-test",
        demo_auth_password_hash=hash_password(
            "fixture-only-password", salt=b"fixed-test-salt-123"
        ),
        demo_auth_session_secret="fixed-test-session-secret-with-32-bytes",
    )
    result = client.get(
        f"/api/v1/products/{product_id}/image-assets/{asset_id}/thumbnail",
        headers={"If-None-Match": "*"},
    )
    assert result.status_code == 401


def test_thumbnail_encoder_failure_preserves_original(
    client, preview_asset, monkeypatch
):
    product_id, asset_id, original, digest = preview_asset
    monkeypatch.setattr(
        product_thumbnail.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1),
    )
    assert (
        client.get(
            f"/api/v1/products/{product_id}/image-assets/{asset_id}/thumbnail"
        ).status_code
        == 503
    )
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    assert not list(original.parent.glob(".thumbnails/*.webp"))


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg required for real preview encoding"
)
def test_real_thumbnail_encoding(preview_asset):
    _, _, original, digest = preview_asset
    preview = product_thumbnail.thumbnail_path(original, digest, "ffmpeg")
    assert preview.read_bytes()[8:12] == b"WEBP"
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(preview),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    assert result.stdout.strip() == "320,240"
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
