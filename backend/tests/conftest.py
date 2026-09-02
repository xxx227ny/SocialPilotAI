from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (  # noqa: F401
    AdCampaign,
    AuthSession,
    BrandKit,
    BrandKitVersion,
    CopyMatrix,
    ExecutionAttempt,
    ExecutionJob,
    LoginThrottle,
    MarketingBrief,
    MarketingStrategy,
    Membership,
    OAuthSession,
    PresentationSnapshot,
    Product,
    ProductAsset,
    ProviderCredential,
    PublishTask,
    SocialAccount,
    User,
    VideoComposition,
    VideoCompositionArtifact,
    VideoCompositionShot,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
    Workspace,
)


@pytest.fixture(autouse=True)
def isolate_settings_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Keep unit tests independent from a developer's live provider settings."""
    for field_name in Settings.model_fields:
        monkeypatch.delenv(field_name.upper(), raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-qwen-smoke",
        action="store_true",
        default=False,
        help="Run tests that make a real Qwen API request",
    )
    parser.addoption(
        "--run-wanx-smoke",
        action="store_true",
        default=False,
        help="Run tests that make a real Wanx API request",
    )
    parser.addoption(
        "--run-happyhorse-smoke",
        action="store_true",
        default=False,
        help="Run tests that make a real HappyHorse API request",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    run_qwen_smoke = config.getoption("--run-qwen-smoke")
    run_wanx_smoke = config.getoption("--run-wanx-smoke")
    run_happyhorse_smoke = config.getoption("--run-happyhorse-smoke")
    skip_real_qwen = pytest.mark.skip(
        reason="real Qwen smoke test requires --run-qwen-smoke"
    )
    skip_real_wanx = pytest.mark.skip(
        reason="real Wanx smoke test requires --run-wanx-smoke"
    )
    skip_real_happyhorse = pytest.mark.skip(
        reason="real HappyHorse smoke test requires --run-happyhorse-smoke"
    )
    skip_unclassified_smoke = pytest.mark.skip(
        reason="external-service smoke test requires a provider-specific marker"
    )
    for item in items:
        is_qwen_smoke = "qwen_smoke" in item.keywords
        is_wanx_smoke = "wanx_smoke" in item.keywords
        is_happyhorse_smoke = "happyhorse_smoke" in item.keywords
        if is_qwen_smoke and not run_qwen_smoke:
            item.add_marker(skip_real_qwen)
        if is_wanx_smoke and not run_wanx_smoke:
            item.add_marker(skip_real_wanx)
        if is_happyhorse_smoke and not run_happyhorse_smoke:
            item.add_marker(skip_real_happyhorse)
        if (
            "smoke" in item.keywords
            and not is_qwen_smoke
            and not is_wanx_smoke
            and not is_happyhorse_smoke
        ):
            item.add_marker(skip_unclassified_smoke)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with testing_session() as session:
        yield session
    # StaticPool owns one in-memory SQLite database. Disposing the engine removes
    # it completely; drop_all() is redundant and emits hundreds of false-positive
    # cycle warnings for the intentional immutable ScriptVersion/VideoProject FKs.
    engine.dispose()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    test_client.close()
    app.dependency_overrides.clear()


@pytest.fixture
def product_payload() -> dict[str, object]:
    return {
        "name": "Portable Blender",
        "category": "Portable Kitchen Appliance",
        "description": "A portable blender for healthy drinks anywhere",
        "selling_points": [
            "Portable design",
            "USB rechargeable",
            "Easy cleaning",
        ],
        "target_markets": ["USA"],
    }
