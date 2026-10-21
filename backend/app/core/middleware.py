import logging
import re
import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from fastapi import FastAPI

logger = logging.getLogger("codemind.audit")

# Redaction patterns for sensitive logs and errors
SENSITIVE_PATTERNS = [
    (re.compile(r':[^:@/]+@'), ':***@'),  # DB passwords in URLs (e.g. postgres:secret@host)
    (re.compile(r'Bearer\s+[A-Za-z0-9\-\._~\+\/]+=*', re.IGNORECASE), 'Bearer [REDACTED]'),
    (re.compile(r'token=[A-Za-z0-9\-\._~\+\/]+', re.IGNORECASE), 'token=[REDACTED]'),
    (re.compile(r'password["\']?\s*:\s*["\'][^"\']+["\']', re.IGNORECASE), 'password: "[REDACTED]"'),
]


def sanitize_sensitive_text(text: str) -> str:
    """Masks database passwords, bearer tokens, and credentials from log strings."""
    if not text:
        return text
    sanitized = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Assigns or preserves an X-Request-ID correlation identifier on every request and response.
    Enables cross-service tracing and auditability without exposing internals.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Check incoming request ID or generate fresh UUID4
        incoming_id = request.headers.get("X-Request-ID")
        if incoming_id and re.match(r'^[a-zA-Z0-9\-_]{8,64}$', incoming_id):
            request_id = incoming_id
        else:
            request_id = str(uuid.uuid4())

        request.state.request_id = request_id
        start_time = time.time()

        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000
            response.headers["X-Request-ID"] = request_id
            
            # Log structured access event without logging credentials
            logger.info(
                f"[{request_id}] {request.method} {request.url.path} - "
                f"Status: {response.status_code} - {duration_ms:.2f}ms"
            )
            return response

        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            safe_message = sanitize_sensitive_text(str(exc))
            logger.error(
                f"[{request_id}] Unhandled error on {request.method} {request.url.path} "
                f"after {duration_ms:.2f}ms: {safe_message}",
                exc_info=True
            )

            # Return structured, safe 500 without disclosing internal database/stack traces
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal Server Error",
                    "detail": "An unexpected error occurred while processing your request.",
                    "request_id": request_id
                },
                headers={"X-Request-ID": request_id}
            )


def register_security_middlewares(app: FastAPI) -> None:
    """Registers correlation ID and audit middlewares on the FastAPI application."""
    app.add_middleware(CorrelationIdMiddleware)
