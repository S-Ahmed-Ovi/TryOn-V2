"""FastAPI application: JSON API + the web page, from one process."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from tryon import __version__
from tryon.api.routes import router
from tryon.catalog.store import Catalog, ensure_catalog
from tryon.config import WEB_DIR, Settings, load_settings
from tryon.recommend.rules import Rules, load_rules

log = logging.getLogger("tryon")


class CachedStatic(StaticFiles):
    """Static files that browsers may keep for a day (URLs carry ?v=<catalog version> to refresh them)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response


def create_app(settings: Settings | None = None, *, catalog: Catalog | None = None,
               detector=None, rules: Rules | None = None, tracker_factory=None) -> FastAPI:
    """Build the app. Tests pass their own catalog / detector / tracker_factory; normally everything is loaded at start-up."""
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.rules = rules or load_rules()
        app.state.catalog = catalog or ensure_catalog(settings, log=print)
        app.state.detector = detector
        app.state.tracker_factory = tracker_factory
        app.state.live_sessions = 0
        if detector is None:
            try:
                from tryon.vision.face_shape import FaceShapeDetector
                app.state.detector = FaceShapeDetector()
            except Exception as exc:  # noqa: BLE001 - the page still works for browsing
                print(f"Warning: face model not available ({exc}). Photo analysis and the live 3D camera are disabled.")
            else:
                from tryon.vision.landmarks import FaceTracker
                app.state.tracker_factory = tracker_factory or FaceTracker
        print(f"{settings.site_name} is ready: {len(app.state.catalog.products)} frames.")
        yield
        if app.state.detector is not None and detector is None:
            app.state.detector.close()

    app = FastAPI(title=f"{settings.site_name} API", version=__version__, lifespan=lifespan,
                  docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    app.include_router(router)

    @app.exception_handler(Exception)
    async def unexpected(_, exc: Exception):
        log.exception("Unhandled error", exc_info=exc)
        return JSONResponse({"detail": "Something went wrong on our side. Please try again."}, status_code=500)

    index_html = (WEB_DIR / "index.html")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home() -> HTMLResponse:
        html = index_html.read_text(encoding="utf-8").replace("{{SITE_NAME}}", settings.site_name)
        return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

    app.mount("/static", CachedStatic(directory=WEB_DIR / "static"), name="static")
    Path(settings.catalog_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/media", CachedStatic(directory=settings.catalog_dir), name="media")
    Path(settings.models_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/models3d", CachedStatic(directory=settings.models_dir), name="models3d")
    return app
