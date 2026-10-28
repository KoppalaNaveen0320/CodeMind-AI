import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import settings
from backend.app.core.middleware import register_security_middlewares
from backend.app.db.session import check_db_connection
from backend.app.api.routes import health, api_v1, views, github_auth, auth, webhooks
from backend.app.services.github_sync_service import GitHubSyncService
from backend.app.services.indexing_service import IndexingService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("codemind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: validate production settings and database connection
    logger.info(f"Starting {settings.APP_NAME} in {settings.APP_ENV} mode...")
    
    if settings.APP_ENV == "production":
        insecure_keys = {
            "codemind-secure-secret-key-32-chars-long!",
            "change-this-in-production-to-a-cryptographically-secure-key",
            "change-this-in-production-env-to-32-chars!",
            ""
        }
        if settings.SECRET_KEY in insecure_keys or len(settings.SECRET_KEY) < 32:
            raise RuntimeError(
                "FATAL CONFIGURATION ERROR: In production mode (APP_ENV=production), SECRET_KEY must be "
                "set to a unique, cryptographically secure string of at least 32 characters in backend/.env."
            )
        if settings.DEBUG:
            raise RuntimeError(
                "FATAL CONFIGURATION ERROR: DEBUG=True is forbidden in production mode. Set DEBUG=False in backend/.env."
            )

    is_connected, dialect, detail = check_db_connection()
    if is_connected:
        logger.info(f"Database connected successfully: {dialect} ({detail})")
        # Recover any jobs left in intermediate states by server restart/crash
        try:
            IndexingService.recover_stale_indexing_jobs()
        except Exception as rec_err:
            logger.warning(f"Failed to recover stale indexing jobs on startup: {rec_err}")
    else:
        if settings.APP_ENV == "production":
            raise RuntimeError(f"FATAL DATABASE ERROR: Production database connection failed: {detail}")
        logger.warning(f"Database readiness check failed on startup: {detail}")

    # Start background GitHub commit synchronization polling if enabled
    GitHubSyncService.start_background_polling()

    yield

    # Shutdown
    GitHubSyncService.stop_background_polling()
    logger.info(f"Shutting down {settings.APP_NAME}...")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="Intelligent repository understanding and change-impact prediction system.",
    docs_url=None if (settings.APP_ENV == "production" and not settings.DEBUG) else "/docs",
    redoc_url=None if (settings.APP_ENV == "production" and not settings.DEBUG) else "/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)

from fastapi.responses import RedirectResponse

@app.get("/api/docs", include_in_schema=False)
async def redirect_api_docs():
    """Redirect legacy /api/docs to canonical Swagger UI at /docs."""
    return RedirectResponse(url="/docs", status_code=307)


# Register CORS middleware
cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Register security, tracing, and audit middlewares
register_security_middlewares(app)

# Mount static files (/static/css, /static/js, /static/assets)
app.mount("/static", StaticFiles(directory=str(settings.STATIC_DIR)), name="static")

# Register API & Page Routes
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(github_auth.router)
app.include_router(api_v1.router)
app.include_router(webhooks.router)
app.include_router(views.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=settings.APP_PORT, reload=settings.DEBUG)
