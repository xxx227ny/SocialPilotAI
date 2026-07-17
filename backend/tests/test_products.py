from fastapi.testclient import TestClient


def create_product(client: TestClient, payload: dict[str, object]) -> dict[str, object]:
    response = client.post("/api/v1/products", json=payload)
    assert response.status_code == 201
    return response.json()


def test_create_product(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product = create_product(client, product_payload)

    assert product["id"] == 1
    assert product["name"] == "Portable Blender"
    assert product["selling_points"] == product_payload["selling_points"]
    assert product["assets"] == []


def test_list_products(
    client: TestClient, product_payload: dict[str, object]
) -> None:
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


def test_update_product(
    client: TestClient, product_payload: dict[str, object]
) -> None:
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


def test_empty_selling_points_fails(
    client: TestClient, product_payload: dict[str, object]
) -> None:
    product_payload["selling_points"] = []

    response = client.post("/api/v1/products", json=product_payload)

    assert response.status_code == 422


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
