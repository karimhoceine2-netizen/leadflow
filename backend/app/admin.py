import asyncio
import hmac
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .auth import COOKIE, LocalAuth, Session, verify_password
from .models import AdminCredentials, AdminSetup, LeadDetail, LeadPage, LeadStatus, StatusUpdate
from .repository import StorageUnavailable, VersionConflict

router = APIRouter(prefix="/api/admin", tags=["Local admin"])


def auth(request: Request) -> LocalAuth:
    return request.app.state.auth


def read_session(request: Request) -> Session:
    return auth(request).get_session(request)


def write_session(request: Request) -> Session:
    return auth(request).require_write(request)


@router.get("/session")
async def session(request: Request):
    identity = auth(request)
    identity.require_local(request)
    try:
        current = identity.get_session(request)
    except HTTPException as error:
        if error.status_code != 401:
            raise
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=401, content={"detail": "Log in om aanvragen te bekijken.", "setup_required": not identity.configured})
    return {"email": current.email, "csrf_token": current.csrf}


@router.post("/setup", status_code=201)
async def setup(credentials: AdminSetup, request: Request, response: Response):
    identity = auth(request)
    try:
        await identity.setup(request, str(credentials.email), credentials.password)
    except OSError:
        raise HTTPException(503, "Het beheeraccount kon niet worden opgeslagen. Controleer de projectmap.") from None
    return identity.start_session(request, response)


@router.post("/login")
async def login(credentials: AdminCredentials, request: Request, response: Response):
    identity = auth(request)
    identity.require_local(request)
    identity.require_origin(request)
    if not identity.configured:
        raise HTTPException(409, "Stel eerst je beheeraccount in.")
    password_ok = await asyncio.to_thread(verify_password, credentials.password, identity.settings.admin_password_hash.get_secret_value())
    email_ok = hmac.compare_digest(str(credentials.email).lower().encode(), identity.settings.admin_email.encode())
    if not password_ok or not email_ok:
        raise HTTPException(401, "E-mailadres of wachtwoord klopt niet.")
    return identity.start_session(request, response)


@router.post("/logout")
async def logout(request: Request, response: Response, current: Session = Depends(write_session)):
    import hashlib
    auth(request).sessions.pop(hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest(), None)
    response.delete_cookie(COOKIE, path="/api/admin", httponly=True, samesite="strict")
    return {"ok": True}


@router.get("/leads", response_model=LeadPage)
async def leads(request: Request, current: Session = Depends(read_session), q: str = Query(default="", max_length=100),
                status: LeadStatus | None = None, page: int = Query(default=1, ge=1, le=1_000_000), page_size: int = Query(default=20, ge=1, le=100)):
    try:
        return await request.app.state.repository.list(q.strip(), status, page, page_size)
    except StorageUnavailable:
        raise HTTPException(503, "Aanvragen laden is tijdelijk niet mogelijk.") from None


@router.get("/leads/{lead_id}", response_model=LeadDetail)
async def lead(lead_id: UUID, request: Request, current: Session = Depends(read_session)):
    try:
        result = await request.app.state.repository.detail(lead_id)
    except StorageUnavailable:
        raise HTTPException(503, "De aanvraag kon niet worden geladen.") from None
    if result is None:
        raise HTTPException(404, "Deze aanvraag bestaat niet.")
    return result


@router.patch("/leads/{lead_id}/status", response_model=LeadDetail)
async def update(lead_id: UUID, change: StatusUpdate, request: Request, current: Session = Depends(write_session)):
    try:
        result = await request.app.state.repository.update_status(lead_id, change, current.email)
    except VersionConflict:
        raise HTTPException(409, "Deze aanvraag is ondertussen gewijzigd. De nieuwste versie is geladen; controleer de status en probeer opnieuw.") from None
    except StorageUnavailable:
        raise HTTPException(503, "De status kon niet worden opgeslagen. Probeer opnieuw.") from None
    if result is None:
        raise HTTPException(404, "Deze aanvraag bestaat niet.")
    return result
