import hashlib

from app.models import ProductAsset
from app.schemas.product import ProductCreate
from app.services.product import ProductService
from app.services.product_asset_storage import ProductAssetStorage, StoredProductImage


def install_normalized_image(monkeypatch):
    """No external decoder or model; use deterministic already-normalized bytes."""

    def normalize(self, file_name, content_type, content):
        digest = hashlib.sha256(content).hexdigest()
        identity = f"product-images/{digest[:2]}/{digest}.png"
        return StoredProductImage(
            identity, self.root / identity, content, "png", "image/png", digest, 64, 64
        )

    monkeypatch.setattr(ProductAssetStorage, "normalize", normalize)


def test_same_image_isolated_across_products_and_safe_to_delete(
    db_session, tmp_path, monkeypatch, product_payload
):
    install_normalized_image(monkeypatch)
    service = ProductService(db_session)
    first = service.create(ProductCreate(**product_payload))
    second = service.create(
        ProductCreate(**{**product_payload, "name": "Different Product"})
    )
    kwargs = dict(
        file_name="image.png",
        content_type="image/png",
        content=b"normalized-test-image",
        storage_root=tmp_path,
        max_bytes=10000,
    )
    first_asset, first_reused = service.upload_asset(first.id, **kwargs)
    second_asset, second_reused = service.upload_asset(second.id, **kwargs)
    assert not first_reused and not second_reused
    assert first_asset.sha256 == second_asset.sha256
    assert first_asset.storage_identity != second_asset.storage_identity
    repeated, reused = service.upload_asset(second.id, **kwargs)
    assert reused and repeated.id == second_asset.id
    storage = ProductAssetStorage(tmp_path, 10000)
    first_path = storage.resolve(first_asset.storage_identity, first_asset.sha256)
    second_path = storage.resolve(second_asset.storage_identity, second_asset.sha256)
    # Upload and deletion use separate request sessions in the HTTP API.
    db_session.expire_all()
    service.delete_product(second.id, storage_root=tmp_path, max_bytes=10000)
    assert first_path.read_bytes() == kwargs["content"]
    assert not second_path.exists()
    assert service.get(first.id).id == first.id


def test_legacy_identity_remains_immutable_when_image_reused(
    db_session, tmp_path, monkeypatch, product_payload
):
    install_normalized_image(monkeypatch)
    service = ProductService(db_session)
    first = service.create(ProductCreate(**product_payload))
    storage = ProductAssetStorage(tmp_path, 10000)
    content = b"legacy-normalized-test-image"
    legacy = storage.normalize("old.png", "image/png", content)
    storage.persist(legacy)
    row = ProductAsset(
        product_id=first.id,
        file_name="old.png",
        file_path=legacy.storage_identity,
        file_type="png",
        content_type="image/png",
        size_bytes=len(content),
        sha256=legacy.sha256,
        width=64,
        height=64,
        storage_identity=legacy.storage_identity,
    )
    db_session.add(row)
    db_session.commit()
    kwargs = dict(
        file_name="new-name.png",
        content_type="image/png",
        content=content,
        storage_root=tmp_path,
        max_bytes=10000,
    )
    repeated, reused = service.upload_asset(first.id, **kwargs)
    assert reused and repeated.id == row.id
    assert repeated.storage_identity == legacy.storage_identity
    second = service.create(ProductCreate(**{**product_payload, "name": "New Owner"}))
    new_asset, reused = service.upload_asset(second.id, **kwargs)
    assert not reused and new_asset.storage_identity != legacy.storage_identity
    db_session.expire_all()
    service.delete_product(second.id, storage_root=tmp_path, max_bytes=10000)
    assert (
        storage.resolve(legacy.storage_identity, legacy.sha256).read_bytes() == content
    )
