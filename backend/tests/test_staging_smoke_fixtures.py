import json

import httpx
import pytest
from deploy.staging import smoke_test
from deploy.staging.smoke_test import seed_validation_account
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import User


def test_fixture_refuses_real_identity(tmp_path):
    with pytest.raises(ValueError, match="Only generated"):
        seed_validation_account(
            tmp_path / "absent.db", "person@example.com", "unused", "test"
        )


def test_fixture_seeds_only_new_synthetic_account(tmp_path):
    database = tmp_path / "fixture.db"
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    email = "smoke-a-20260905120000abcdef@invalid.example"
    seed_validation_account(
        database, email, "FixturePassword-12345", "Smoke Workspace A"
    )
    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == email))
        assert user is not None and user.email_verified_at is not None
    engine.dispose()


def test_fixture_login_uses_current_api_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke_test, "seed_validation_account", lambda *args: None)

    def handle(request):
        assert request.url.path == "/api/v1/auth/login"
        assert json.loads(request.content) == {
            "username": "fixture",
            "password": "test-password",
        }
        return httpx.Response(
            200,
            json={"workspace_id": 1},
            headers={"set-cookie": "session=test; HttpOnly; Secure; SameSite=lax"},
        )

    with httpx.Client(
        base_url="https://test.local", transport=httpx.MockTransport(handle)
    ) as client:
        assert smoke_test.register(
            client, "fixture", "test-password", "test", tmp_path
        ) == {"workspace_id": 1}
