import logging
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.extraction.config import Settings
from src.extraction.exceptions import ExtractionError
from src.extraction.router import router
from src.extraction.worker import Worker

logger = logging.getLogger(__name__)


def metadata(request, status):
    state = request.state
    return dict(
        request_id=state.request_id,
        request_payload=getattr(state, "payload", {}),
        filename=getattr(state, "filename", None),
        media_type=getattr(state, "media_type", None),
        file_fingerprint=getattr(state, "fingerprint", None),
        pages=getattr(state, "pages", None),
        time_input=state.time_input,
        time_response=datetime.now(UTC).isoformat(),
        response_code=status,
        elapsed_ms=round((time.monotonic() - state.started) * 1000, 2),
    )


@asynccontextmanager
async def lifespan(app):
    worker = Worker(Settings())
    app.state.worker = worker
    await worker.start()
    try:
        yield
    finally:
        await worker.close()


settings = Settings()
app = FastAPI(
    title="Docling extraction",
    lifespan=lifespan,
    openapi_url="/openapi.json"
    if settings.environment in {"local", "staging"}
    else None,
)
app.state.metadata = metadata
app.include_router(router)


@app.middleware("http")
async def timing(request: Request, call_next):
    request.state.request_id = str(uuid4())
    request.state.started = time.monotonic()
    request.state.time_input = datetime.now(UTC).isoformat()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    logger.info(
        "request_id=%s status=%s elapsed_ms=%s",
        request.state.request_id,
        response.status_code,
        metadata(request, response.status_code)["elapsed_ms"],
    )
    return response


@app.exception_handler(ExtractionError)
async def extraction_error(request, exc):
    return JSONResponse(
        {"detail": exc.detail, "metadata": metadata(request, exc.status)},
        status_code=exc.status,
        headers={"Retry-After": "1"} if exc.status == 503 else None,
    )


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    logger.error(
        "request_id=%s unexpected_error=%s",
        request.state.request_id,
        type(exc).__name__,
    )
    return JSONResponse(
        {"detail": "Extraction failed", "metadata": metadata(request, 500)},
        status_code=500,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(
        {"detail": "Invalid request fields", "metadata": metadata(request, 422)},
        status_code=422,
    )


@app.get("/health/live")
async def live():
    return {"status": "ok"}


@app.get("/health/ready")
async def ready():
    worker = getattr(app.state, "worker", None)
    return JSONResponse(
        {"ready": bool(worker and worker.ready)},
        status_code=200 if worker and worker.ready else 503,
    )
