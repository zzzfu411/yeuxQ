"""FastAPI 应用工厂。"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from yeuxq.api.deps import get_v1_service_provider, init_container, shutdown_container
from yeuxq.api.routes_analyze import router as analyze_router
from yeuxq.api.routes_backtest import router as backtest_router
from yeuxq.api.routes_market import router as market_router
from yeuxq.api.routes_orderflow import router as orderflow_router
from yeuxq.api.routes_research import router as research_router
from yeuxq.api.routes_scan import router as scan_router
from yeuxq.api.routes_v1 import create_v1_router
from yeuxq.security import RuntimeSecrets, validate_serve_security
from yeuxq.settings import PACKAGE_ROOT, PROJECT_ROOT, Settings, get_settings

log = logging.getLogger("yeuxq")

_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _resolved_tls_paths(settings: Settings) -> tuple[Path | None, Path | None]:
    cert = (
        settings.resolve_file_path(settings.app.tls_certfile) if settings.app.tls_certfile else None
    )
    key = settings.resolve_file_path(settings.app.tls_keyfile) if settings.app.tls_keyfile else None
    return cert, key


def create_app(
    settings: Settings | None = None,
    runtime_secrets: RuntimeSecrets | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    runtime_secrets = runtime_secrets or RuntimeSecrets.from_env()
    certfile, keyfile = _resolved_tls_paths(settings)
    security = validate_serve_security(
        host=settings.app.host,
        access_token=runtime_secrets.access_token,
        allowed_hosts=settings.app.allowed_hosts,
        tls_certfile=certfile,
        tls_keyfile=keyfile,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        init_container(settings, runtime_secrets)
        log.info("%s v%s starting", settings.app.name, settings.app.version)
        yield
        shutdown_container()
        log.info("shutdown complete")

    app = FastAPI(
        title=settings.app.name,
        version=settings.app.version,
        lifespan=lifespan,
    )
    app.state.serve_security = security
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(security.allowed_hosts),
    )

    if security.requires_api_auth:
        assert runtime_secrets.access_token is not None
        expected_token = runtime_secrets.access_token.get_secret_value()

        @app.middleware("http")
        async def require_bearer(request: Request, call_next):
            scheme, separator, credentials = request.headers.get("authorization", "").partition(" ")
            authorized = (
                separator == " "
                and scheme.lower() == "bearer"
                and hmac.compare_digest(credentials, expected_token)
            )
            if not authorized:
                return JSONResponse(
                    {"detail": "authentication required"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return await call_next(request)

    app.include_router(create_v1_router(get_v1_service_provider()))
    app.include_router(market_router)
    app.include_router(analyze_router)
    app.include_router(backtest_router)
    app.include_router(scan_router)
    app.include_router(research_router)
    app.include_router(orderflow_router)

    integration_dir = PROJECT_ROOT / "integration" if PROJECT_ROOT is not None else None
    if integration_dir is not None and integration_dir.is_dir():
        app.mount(
            "/integration",
            StaticFiles(directory=str(integration_dir), html=True),
            name="integration",
        )
    else:

        @app.get("/integration", include_in_schema=False)
        @app.get("/integration/{resource:path}", include_in_schema=False)
        def integration_unavailable(resource: str = ""):
            return JSONResponse(
                {
                    "available": False,
                    "detail": "integration status is available only from a source checkout",
                },
                status_code=503,
            )

    web_dir = PACKAGE_ROOT / "web"
    if web_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

        @app.get("/")
        def index():
            index_path = web_dir / "index.html"
            if index_path.is_file():
                return FileResponse(index_path, headers=_NO_CACHE)
            return {"message": "yeuxQ API ready", "docs": "/docs"}
    else:

        @app.get("/")
        def package_assets_unavailable():
            return JSONResponse(
                {"detail": "yeuxQ web assets are unavailable", "docs": "/docs"},
                status_code=503,
            )

    return app
