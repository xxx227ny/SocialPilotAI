from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.init_db import seed_development_data


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    seed_development_data()
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="SocialPilot AI API",
        description="跨境电商 AI 社媒营销增长平台 API",
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    register_exception_handlers(application)
    return application


app = create_app()
