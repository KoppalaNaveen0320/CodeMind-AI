from fastapi import APIRouter, Response, status
from backend.app.core.config import settings
from backend.app.db.session import check_db_connection, get_db_diagnostics
from backend.app.schemas.health import HealthResponse, ReadinessResponse
from backend.app.integrations.llm.service import get_llm_provider
from backend.app.integrations.embeddings.service import get_embedding_provider

router = APIRouter(tags=["Health & Readiness"])


@router.get("/health", response_model=HealthResponse)
@router.get("/healthz", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Liveness probe - confirms the FastAPI application process is up and responding."""
    return HealthResponse(
        status="ok",
        app=settings.APP_NAME,
        version="0.1.0",
        environment=settings.APP_ENV,
    )


@router.get("/ready", response_model=ReadinessResponse)
@router.get("/readyz", response_model=ReadinessResponse)
def get_readiness(response: Response) -> ReadinessResponse:
    """
    Readiness probe - confirms database connectivity, pgvector, and local AI availability.
    Returns HTTP 200 if database is reachable, HTTP 503 if database is unavailable.
    """
    is_connected, dialect, detail = check_db_connection()
    db_diag = get_db_diagnostics()
    llm_provider = get_llm_provider()
    llm_diag = llm_provider.get_configuration_status()
    embed_provider = get_embedding_provider()
    embed_diag = embed_provider.get_configuration_status()

    if is_connected:
        return ReadinessResponse(
            status="ready",
            database="connected",
            dialect=db_diag.get("dialect") or dialect,
            detail=detail or db_diag.get("detail"),
            pgvector_available=db_diag.get("pgvector_available", False),
            ai_provider=settings.AI_PROVIDER,
            ollama_service_available=embed_diag.get("service_available", False),
            llm_model_available=llm_diag.get("model_available", False),
            embedding_model_available=embed_diag.get("model_available", False),
        )
    else:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(
            status="not_ready",
            database="disconnected",
            dialect=db_diag.get("dialect") or dialect,
            detail=detail or db_diag.get("detail"),
            pgvector_available=False,
            ai_provider=settings.AI_PROVIDER,
            ollama_service_available=embed_diag.get("service_available", False),
            llm_model_available=llm_diag.get("model_available", False),
            embedding_model_available=embed_diag.get("model_available", False),
        )
