import pytest
from sqlalchemy import event, select, text

from app.core.config import get_settings
from app.main import app
from app.models import (
    AuthSession,
    ExecutionJob,
    Membership,
    Product,
    ProviderCredential,
    User,
    Workspace,
)
from tests.test_user_auth import PASSWORD, user_auth_settings

URL = "/api/v1/auth/delete-account"


def register(client, email="delete-owner@example.com"):
    app.dependency_overrides[get_settings] = lambda: user_auth_settings()
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 201
    return response.json()


def request(client, **overrides):
    return client.post(
        URL,
        json={
            "current_password": PASSWORD,
            "confirmation": "注销当前账号",
            **overrides,
        },
    )


@pytest.mark.parametrize("foreign_keys", [False, True])
def test_deletion_isolated_and_reregistration_is_fresh(
    client, db_session, foreign_keys
):
    db_session.execute(text(f"PRAGMA foreign_keys = {int(foreign_keys)}"))
    other = register(client, "delete-other@example.com")
    other_cookie = client.cookies.get("socialpilot_session")
    owner = register(client)
    old_cookie = client.cookies.get("socialpilot_session")
    own_product = Product(
        workspace_id=owner["workspace_id"],
        name="Delete me",
        selling_points=["demo"],
        display_number=1,
    )
    other_product = Product(
        workspace_id=other["workspace_id"],
        name="Keep me",
        selling_points=["safe"],
        display_number=1,
    )
    db_session.add_all(
        [
            own_product,
            other_product,
            ProviderCredential(
                workspace_id=owner["workspace_id"],
                provider="dashscope",
                secret_ciphertext="test-encrypted-only",
                encryption_key_id="test",
                secret_hint="test",
            ),
        ]
    )
    db_session.commit()
    own_id, other_id = own_product.id, other_product.id
    response = request(client)
    assert response.status_code == 200, response.text
    assert "Max-Age=0" in response.headers["set-cookie"]
    db_session.expire_all()
    assert db_session.get(Product, own_id) is None
    assert db_session.get(Product, other_id) is not None
    assert db_session.scalar(select(ProviderCredential)) is None
    assert (
        db_session.scalar(
            select(AuthSession).where(AuthSession.user_id == owner["user_id"])
        )
        is None
    )
    assert db_session.get(User, owner["user_id"]).status == "DELETED"
    assert db_session.get(Workspace, owner["workspace_id"]).status == "DELETED"
    assert not db_session.execute(text("PRAGMA foreign_key_check")).all()
    client.cookies.set("socialpilot_session", old_cookie)
    assert client.get("/api/v1/products").status_code == 401
    client.cookies.clear()
    fresh = register(client)
    assert fresh["user_id"] != owner["user_id"]
    assert fresh["workspace_id"] != owner["workspace_id"]
    assert db_session.get(Workspace, fresh["workspace_id"]).next_product_number == 1
    assert client.get("/api/v1/products").json() == []
    created = client.post(
        "/api/v1/products",
        json={
            "name": "Fresh",
            "category": "Demo",
            "description": "Fresh demo",
            "selling_points": ["fresh"],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["display_number"] == 1
    client.cookies.clear()
    client.cookies.set("socialpilot_session", other_cookie)
    assert client.get("/api/v1/auth/session").json()["authenticated"]


def test_wrong_password_and_confirmation_do_not_delete(client, db_session):
    owner = register(client)
    assert request(client, confirmation="yes").status_code == 422
    assert request(client, current_password="wrong").status_code == 403
    assert client.get("/api/v1/auth/session").json()["authenticated"]
    assert db_session.get(User, owner["user_id"]).status == "ACTIVE"


def test_wrong_password_is_throttled(client):
    register(client)
    app.dependency_overrides[get_settings] = lambda: user_auth_settings(
        user_auth_login_max_failures=3
    )
    assert request(client, current_password="wrong").status_code == 403
    assert request(client, current_password="wrong").status_code == 403
    assert request(client, current_password="wrong").status_code == 403
    assert request(client).status_code == 429


def test_requires_real_authenticated_account(client):
    app.dependency_overrides[get_settings] = lambda: user_auth_settings()
    assert request(client).status_code == 401


def test_shared_workspace_refused(client, db_session):
    other = register(client, "member@example.com")
    owner = register(client)
    db_session.add(
        Membership(
            user_id=other["user_id"], workspace_id=owner["workspace_id"], role="MEMBER"
        )
    )
    db_session.commit()
    assert request(client).status_code == 409
    assert db_session.get(User, owner["user_id"]).status == "ACTIVE"


@pytest.mark.parametrize("job_status", ["QUEUED", "PAUSED", "SUBMIT_UNKNOWN"])
def test_unfinished_jobs_refused(client, db_session, job_status):
    owner = register(client)
    db_session.add(
        ExecutionJob(
            workspace_id=owner["workspace_id"],
            job_type="TEST",
            source_type="product",
            source_id=1,
            input_digest="a" * 64,
            idempotency_key="test-delete",
            status=job_status,
            uncertain=job_status == "SUBMIT_UNKNOWN",
        )
    )
    db_session.commit()
    response = request(client)
    assert response.status_code == 409, response.text
    assert db_session.get(User, owner["user_id"]).status == "ACTIVE"


def test_failed_transaction_restores_data(client, db_session):
    owner = register(client)
    db_session.add(
        Product(
            workspace_id=owner["workspace_id"],
            name="Keep on rollback",
            selling_points=["safe"],
        )
    )
    db_session.commit()
    engine = db_session.get_bind()

    def fail_update(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE users SET"):
            raise RuntimeError("Simulated database failure")

    event.listen(engine, "before_cursor_execute", fail_update)
    try:
        with pytest.raises(RuntimeError, match="Simulated"):
            request(client)
    finally:
        event.remove(engine, "before_cursor_execute", fail_update)
    db_session.expire_all()
    assert db_session.get(User, owner["user_id"]).status == "ACTIVE"
    assert (
        db_session.scalar(
            select(Product).where(Product.workspace_id == owner["workspace_id"])
        )
        is not None
    )
    assert client.get("/api/v1/auth/session").json()["authenticated"]


def test_cyclic_script_versions_and_batch_parent_deleted(client, db_session):
    from app.models import (
        BatchVideoJob,
        PresentationSnapshot,
        ProductAsset,
        VideoScriptVersion,
    )
    from tests.test_three_platform_video_preflight import create_three_platform_sources

    owner = register(client)
    product, asset, _ = create_three_platform_sources(db_session)
    product.workspace_id = owner["workspace_id"]
    db_session.add(
        PresentationSnapshot(
            product_id=product.id,
            schema_version=1,
            digest="d" * 64,
            campaign_ids=[],
            missing_sections=[],
            snapshot_payload={"private": "test"},
        )
    )
    db_session.commit()
    db_session.execute(text("PRAGMA foreign_keys = ON"))
    response = request(client)
    assert response.status_code == 200, response.text
    assert db_session.scalar(select(VideoScriptVersion)) is None
    assert db_session.scalar(select(BatchVideoJob)) is None
    assert db_session.scalar(select(ProductAsset)) is None
    assert db_session.scalar(select(PresentationSnapshot)) is None
    assert not db_session.execute(text("PRAGMA foreign_key_check")).all()


def test_other_product_reference_refuses_deletion(client, db_session):
    # Cross-workspace FK corruption must fail closed, not expand deletion scope.
    from app.models import BatchVideoVariant
    from tests.test_three_platform_video_preflight import create_three_platform_sources

    other = register(client, "outsider@example.com")
    owner = register(client)
    product, _, _ = create_three_platform_sources(db_session)
    product.workspace_id = owner["workspace_id"]
    outsider = Product(
        workspace_id=other["workspace_id"], name="Other", selling_points=["safe"]
    )
    db_session.add(outsider)
    db_session.flush()
    variant = db_session.scalar(select(BatchVideoVariant))
    variant.product_id = outsider.id
    db_session.commit()
    assert request(client).status_code == 409
    assert db_session.get(User, owner["user_id"]).status == "ACTIVE"
