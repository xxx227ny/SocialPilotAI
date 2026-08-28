import struct
import zlib

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app


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


def create_product(client: TestClient, payload: dict[str, object]) -> dict[str, object]:
    response = client.post("/api/v1/products", json=payload)
    assert response.status_code == 201
    return response.json()


def test_create_product(client: TestClient, product_payload: dict[str, object]) -> None:
    product = create_product(client, product_payload)

    assert product["id"] == 1
    assert product["name"] == "Portable Blender"
    assert product["selling_points"] == product_payload["selling_points"]
    assert product["assets"] == []


def test_list_products(client: TestClient, product_payload: dict[str, object]) -> None:
    create_product(client, product_payload)

    response = client.get("/api/v1/products")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["name"] == "Portable Blender"


def test_get_product_detail(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = create_product(client, product_payload)

    response = client.get(f"/api/v1/products/{product['id']}")

    assert response.status_code == 200
    assert response.json()["description"] == product_payload["description"]


def test_update_product(client: TestClient, product_payload: dict[str, object]) -> None:
    product = create_product(client, product_payload)

    response = client.patch(
        f"/api/v1/products/{product['id']}",
        json={"category": "Kitchen & Dining", "target_markets": ["Canada"]},
    )

    assert response.status_code == 200
    assert response.json()["category"] == "Kitchen & Dining"
    assert response.json()["target_markets"] == ["Canada"]


def test_empty_product_name_fails(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product_payload["name"] = "   "

    response = client.post("/api/v1/products", json=product_payload)

    assert response.status_code == 422


def test_empty_product_category_fails(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product_payload["category"] = "   "

    response = client.post("/api/v1/products", json=product_payload)

    assert response.status_code == 422


def test_short_product_description_fails(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product_payload["description"] = "Too short"

    response = client.post("/api/v1/products", json=product_payload)

    assert response.status_code == 422


def test_empty_selling_points_fails(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product_payload["selling_points"] = []

    response = client.post("/api/v1/products", json=product_payload)

    assert response.status_code == 422


def test_blank_selling_point_fails(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product_payload["selling_points"] = ["USB rechargeable", "   "]

    response = client.post("/api/v1/products", json=product_payload)

    assert response.status_code == 422


def test_more_than_eight_selling_points_fails(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product_payload["selling_points"] = [f"Selling point {index}" for index in range(9)]

    response = client.post("/api/v1/products", json=product_payload)

    assert response.status_code == 422


def test_create_product_trims_and_deduplicates_selling_points(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product_payload["name"] = "  USB Portable Blender  "
    product_payload["category"] = "  Portable Kitchen Appliance  "
    product_payload["description"] = (
        "  A rechargeable portable blender designed for fresh drinks anywhere.  "
    )
    product_payload["selling_points"] = [
        "  USB rechargeable  ",
        "Compact portable design",
        "USB rechargeable",
    ]

    response = client.post("/api/v1/products", json=product_payload)

    assert response.status_code == 201
    product = response.json()
    assert product["name"] == "USB Portable Blender"
    assert product["category"] == "Portable Kitchen Appliance"
    assert product["description"] == (
        "A rechargeable portable blender designed for fresh drinks anywhere."
    )
    assert product["selling_points"] == [
        "USB rechargeable",
        "Compact portable design",
    ]


def test_jpg_asset_succeeds(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = create_product(client, product_payload)

    response = client.post(
        f"/api/v1/products/{product['id']}/assets",
        json={
            "file_name": "blender-hero.jpg",
            "file_path": "assets/products/blender-hero.jpg",
            "file_type": "jpg",
        },
    )

    assert response.status_code == 201
    assert response.json()["file_type"] == "jpg"
    assert response.json()["product_id"] == product["id"]


def test_exe_asset_fails(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = create_product(client, product_payload)

    response = client.post(
        f"/api/v1/products/{product['id']}/assets",
        json={
            "file_name": "unsafe.exe",
            "file_path": "assets/products/unsafe.exe",
            "file_type": "exe",
        },
    )

    assert response.status_code == 422


def test_controlled_product_image_upload_is_content_addressed_and_reused(
    client: TestClient, product_payload: dict[str, object], tmp_path
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        enable_real_product_video=True,
        product_asset_storage_root=str(tmp_path / "images"),
    )
    product = create_product(client, product_payload)
    files = {"file": ("product.png", png_bytes(), "image/png")}
    first = client.post(f"/api/v1/products/{product['id']}/image-assets", files=files)
    second = client.post(f"/api/v1/products/{product['id']}/image-assets", files=files)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert first.json()["width"] == 1080
    assert first.json()["height"] == 1920
    assert len(first.json()["sha256"]) == 64
    app.dependency_overrides.pop(get_settings, None)


def test_product_image_rejects_spoofed_mime_without_database_write(
    client: TestClient, product_payload: dict[str, object], tmp_path
) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        enable_real_product_video=True,
        product_asset_storage_root=str(tmp_path / "images"),
    )
    product = create_product(client, product_payload)
    response = client.post(
        f"/api/v1/products/{product['id']}/image-assets",
        files={"file": ("unsafe.jpg", b"not-an-image", "image/jpeg")},
    )
    assert response.status_code == 422
    assert client.get(f"/api/v1/products/{product['id']}").json()["assets"] == []
    app.dependency_overrides.pop(get_settings, None)


def test_delete_unused_uploaded_asset_removes_record_and_file(
    client: TestClient, product_payload: dict[str, object], tmp_path
) -> None:
    storage_root = tmp_path / "images"
    app.dependency_overrides[get_settings] = lambda: Settings(
        enable_real_product_video=True,
        product_asset_storage_root=str(storage_root),
    )
    product = create_product(client, product_payload)
    uploaded = client.post(
        f"/api/v1/products/{product['id']}/image-assets",
        files={"file": ("product.png", png_bytes(), "image/png")},
    ).json()
    assert len(list(storage_root.rglob("*.png"))) == 1

    response = client.delete(
        f"/api/v1/products/{product['id']}/image-assets/{uploaded['id']}"
    )

    assert response.status_code == 204
    assert client.get(f"/api/v1/products/{product['id']}").json()["assets"] == []
    assert list(storage_root.rglob("*.png")) == []
    app.dependency_overrides.pop(get_settings, None)


def test_delete_unused_product_removes_its_uploaded_assets(
    client: TestClient, product_payload: dict[str, object], tmp_path
) -> None:
    storage_root = tmp_path / "images"
    app.dependency_overrides[get_settings] = lambda: Settings(
        enable_real_product_video=True,
        product_asset_storage_root=str(storage_root),
    )
    product = create_product(client, product_payload)
    client.post(
        f"/api/v1/products/{product['id']}/image-assets",
        files={"file": ("product.png", png_bytes(), "image/png")},
    )

    response = client.delete(f"/api/v1/products/{product['id']}")

    assert response.status_code == 204
    assert client.get(f"/api/v1/products/{product['id']}").status_code == 404
    assert list(storage_root.rglob("*.png")) == []
    app.dependency_overrides.pop(get_settings, None)


def test_delete_product_with_business_history_is_safely_rejected(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = create_product(client, product_payload)
    task = client.post(
        "/api/v1/marketing-tasks",
        json={
            "product_id": product["id"],
            "audience": "Busy professionals",
            "language": "English",
            "platforms": ["TikTok"],
            "tone": "Practical",
            "objective": "Increase qualified traffic",
        },
    )
    assert task.status_code == 201

    response = client.delete(f"/api/v1/products/{product['id']}")

    assert response.status_code == 409
    assert "不能删除" in response.json()["error"]["message"]
    assert client.get(f"/api/v1/products/{product['id']}").status_code == 200


def test_delete_unknown_product_or_asset_is_safe(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = create_product(client, product_payload)

    assert client.delete("/api/v1/products/999").status_code == 404
    assert (
        client.delete(f"/api/v1/products/{product['id']}/image-assets/999").status_code
        == 404
    )
