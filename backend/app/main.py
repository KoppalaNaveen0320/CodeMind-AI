import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.core.config import settings
from backend.app.core.middleware import register_security_middlewares
from backend.app.db.session import check_db_connection
from backend.app.api.routes import health, api_v1, views, github_auth, auth

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("codemind")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: validate production settings and database connection
    logger.info(f"Starting {settings.APP_NAME} in {settings.APP_ENV} mode...")
    
    if settings.APP_ENV == "production":
        if settings.SECRET_KEY == "codemind-secure-secret-key-32-chars-long!":
            logger.critical("SECURITY WARNING: Using default SECRET_KEY in production! Set SECRET_KEY in backend/.env immediately.")
        if settings.DEBUG:
            logger.warning("SECURITY WARNING: DEBUG=True is active in production environment.")

    is_connected, dialect, detail = check_db_connection()
    if is_connected:
        logger.info(f"Database connected successfully: {dialect} ({detail})")
    else:
        logger.warning(f"Database readiness check failed on startup: {detail}")
    yield
    # Shutdown
    logger.info(f"Shutting down {settings.APP_NAME}...")


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    description="Intelligent repository understanding and change-impact prediction system.",
    docs_url=None if (settings.APP_ENV == "production" and not settings.DEBUG) else "/api/docs",
    redoc_url=None if (settings.APP_ENV == "production" and not settings.DEBUG) else "/api/redoc",
    lifespan=lifespan
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
app.include_router(views.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=settings.APP_PORT, reload=settings.DEBUG)
