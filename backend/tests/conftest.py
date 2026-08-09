from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (  # noqa: F401
    AdCampaign,
    BrandKit,
    BrandKitVersion,
    CopyMatrix,
    ExecutionAttempt,
    ExecutionJob,
    MarketingBrief,
    MarketingStrategy,
    OAuthSession,
    PresentationSnapshot,
    Product,
    ProductAsset,
    PublishTask,
    SocialAccount,
    VideoProject,
    VideoRenderArtifact,
    VideoRenderTask,
)


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


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    run_qwen_smoke = config.getoption("--run-qwen-smoke")
    run_wanx_smoke = config.getoption("--run-wanx-smoke")
    skip_real_qwen = pytest.mark.skip(
        reason="real Qwen smoke test requires --run-qwen-smoke"
    )
    skip_real_wanx = pytest.mark.skip(
        reason="real Wanx smoke test requires --run-wanx-smoke"
    )
    skip_unclassified_smoke = pytest.mark.skip(
        reason="external-service smoke test requires a provider-specific marker"
    )
    for item in items:
        is_qwen_smoke = "qwen_smoke" in item.keywords
        is_wanx_smoke = "wanx_smoke" in item.keywords
        if is_qwen_smoke and not run_qwen_smoke:
            item.add_marker(skip_real_qwen)
        if is_wanx_smoke and not run_wanx_smoke:
            item.add_marker(skip_real_wanx)
        if (
            "smoke" in item.keywords
            and not is_qwen_smoke
            and not is_wanx_smoke
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
    testing_session = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    with testing_session() as session:
        yield session
    Base.metadata.drop_all(engine)
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
