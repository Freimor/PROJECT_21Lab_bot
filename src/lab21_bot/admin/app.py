from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from lab21_bot.admin.routes import api_router
from lab21_bot.config import Settings, get_settings
from lab21_bot.db import bootstrap_database, create_engine, create_session_factory

logger = structlog.get_logger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        factory = create_session_factory(engine)
        await bootstrap_database(engine, factory, settings)
        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = factory
        logger.info("admin_started", host=settings.admin_host, port=settings.admin_port)
        try:
            yield
        finally:
            await engine.dispose()

    upload_root = Path(settings.upload_dir)
    upload_root.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Lab21 Admin", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="lab21_admin",
        same_site="lax",
        https_only=settings.admin_base_url.startswith("https://"),
        max_age=60 * 60 * 12,
    )
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/uploads", StaticFiles(directory=str(upload_root)), name="uploads")
    app.include_router(api_router)
    return app


def run() -> None:
    settings = get_settings()
    if not settings.admin_enabled:
        raise SystemExit("ADMIN_ENABLED=false — веб-админка отключена")
    uvicorn.run(
        "lab21_bot.admin.app:create_app",
        factory=True,
        host=settings.admin_host,
        port=settings.admin_port,
        log_level=settings.log_level.lower(),
    )
