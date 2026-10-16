import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from uuid import UUID

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .auth import LocalAuth
from .admin import router as admin_router
from .automation import router as automation_router, Worker
from .models import LeadCreate, LeadResponse
from .repository import DemoRepository, IdempotencyConflict, StorageUnavailable

logger = logging.getLogger("leadflow")


def create_app(settings: Settings | None = None, *, start_automation_worker: bool = True) -> FastAPI:
    settings = settings or Settings.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False, trust_env=False) as client:
            app.state.repository = DemoRepository(settings.demo_db_path)
            await app.state.repository.initialize()
            worker = (
                asyncio.create_task(Worker(settings, client).run())
                if settings.automation_enabled and start_automation_worker
                else None
            )
            try:
                yield
            finally:
                if worker:
                    worker.cancel()
                    with suppress(asyncio.CancelledError):
                        await worker

    app = FastAPI(
        title="Magnifize LeadFlow API",
        version="0.3.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env != "production" else None,
    )
    app.state.settings = settings
    app.state.auth = LocalAuth(settings)
    app.include_router(admin_router)
    app.include_router(automation_router)
    # Local limiter. Multiple production workers need a shared proxy limiter.
    buckets: dict[str, tuple[float, int]] = {}

    @app.middleware("http")
    async def protect_intake(request: Request, call_next):
        is_auth = request.url.path in {"/api/admin/login", "/api/admin/setup"}
        if request.method == "POST" and (request.url.path == "/api/leads" or is_auth):
            now = time.monotonic()
            for ip in [ip for ip, (started, _) in buckets.items() if now - started >= 60]:
                del buckets[ip]
            ip = (request.client.host if request.client else "unknown") + (":auth" if is_auth else ":intake")
            started, count = buckets.get(ip, (now, 0))
            limit = settings.auth_rate_limit_per_minute if is_auth else settings.rate_limit_per_minute
            if count >= limit or (ip not in buckets and len(buckets) >= 10000):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Te veel aanvragen. Wacht een minuut en probeer opnieuw."},
                    headers={"Retry-After": "60"},
                )
            buckets[ip] = (started, count + 1)
        if request.method in {"POST", "PATCH"} and request.url.path.startswith("/api/"):
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 16384:
                    return JSONResponse(status_code=413, content={"detail": "De aanvraag is te groot."})
                body.extend(chunk)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["POST", "GET", "PATCH"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Do not echo raw input (personal data) in error responses.
        errors = [{"field": str(error["loc"][-1]), "message": error["msg"]} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": "Controleer de ingevulde gegevens.", "errors": errors})

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/leads", response_model=LeadResponse, status_code=201)
    async def create_lead(
        lead: LeadCreate,
        request: Request,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        try:
            key = UUID(idempotency_key) if idempotency_key else None
        except ValueError:
            key = None
        if key is None or key.version != 4:
            raise HTTPException(400, "Een geldige Idempotency-Key (UUID v4) is verplicht.")
        try:
            result = await request.app.state.repository.create(lead, key)
        except IdempotencyConflict:
            raise HTTPException(409, "Deze verzendsleutel is al gebruikt voor andere gegevens.") from None
        except StorageUnavailable:
            logger.error("Lead storage unavailable")
            raise HTTPException(503, "Opslaan is tijdelijk niet mogelijk. Probeer opnieuw.") from None
        if result.duplicate:
            response.status_code = 200
        return result

    return app


app = create_app()
