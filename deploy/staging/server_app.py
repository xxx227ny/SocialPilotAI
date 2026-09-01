"""Hardened staging web entry serving the API and the built frontend."""

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import server_runtime  # noqa: F401
from app.main import app
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

PUBLIC_ORIGIN = os.environ["SOCIALPILOT_PUBLIC_ORIGIN"].rstrip("/")
PUBLIC_HOST = urlsplit(PUBLIC_ORIGIN).hostname
if not PUBLIC_HOST or urlsplit(PUBLIC_ORIGIN).scheme != "https":
    raise RuntimeError("SOCIALPILOT_PUBLIC_ORIGIN must be an HTTPS origin")


class SameOriginWrites:
    def __init__(self, application):
        self.application = application

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in {
            "GET",
            "HEAD",
            "OPTIONS",
        }:
            headers = dict(scope.get("headers", []))
            origin = headers.get(b"origin", b"").decode("latin1").rstrip("/")
            cross_site = headers.get(b"sec-fetch-site") == b"cross-site"
            if cross_site or (origin and origin != PUBLIC_ORIGIN):
                response = JSONResponse(
                    {"detail": "Cross-origin write denied"}, status_code=403
                )
                await response(scope, receive, send)
                return
        await self.application(scope, receive, send)


class PublicFrontend(StaticFiles):
    async def get_response(self, path, scope):
        if path != "." and path.startswith(
            ("api/", ".", "docs", "redoc", "openapi")
        ):
            raise HTTPException(status_code=404)
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or Path(path).suffix:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and not Path(path).suffix:
            return await super().get_response("index.html", scope)
        if response.status_code in {200, 304} and re.fullmatch(
            r"assets/[\w-]+-[\w-]{8,}\.(?:js|css)", path
        ):
            response.headers["Cache-Control"] = (
                "public, max-age=31536000, immutable"
            )
        return response


app.router.routes[:] = [
    route
    for route in app.router.routes
    if getattr(route, "path", "")
    not in {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
]
app.add_middleware(SameOriginWrites)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[PUBLIC_HOST, "127.0.0.1", "localhost"],
)
app.mount(
    "/",
    PublicFrontend(directory=Path(__file__).parent / "frontend", html=True),
)
