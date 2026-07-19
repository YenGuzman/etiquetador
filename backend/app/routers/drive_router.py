# -*- coding: utf-8 -*-
import json
import os
import threading
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import models, schemas, config, drive_sync
from ..database import get_db, SessionLocal
from ..auth import get_current_admin, get_current_user

router = APIRouter(prefix="/api/drive", tags=["drive"])

PUBLIC_BASE_URL = config.PUBLIC_BASE_URL
REDIRECT_URI = f"{PUBLIC_BASE_URL}/api/drive/oauth/callback"

# Estado del trabajo de subida en curso (proceso único; suficiente para un
# despliegue de un solo worker, que es lo esperado para este proyecto).
_upload_job = {
    "status": "idle",  # idle | running | completed | error | cancelled
    "done": 0,
    "total": 0,
    "current_name": "",
    "message": "",
}
_upload_cancel_event = threading.Event()
_upload_lock = threading.Lock()


def _get_settings(db: Session) -> models.DriveSettings:
    settings = db.query(models.DriveSettings).first()
    if not settings:
        settings = models.DriveSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def _get_valid_credentials(db: Session, settings: models.DriveSettings):
    if not settings.token_json:
        raise HTTPException(400, "Todavía no se ha autorizado el acceso a Google Drive (falta iniciar sesión con Google).")
    creds = drive_sync.credentials_from_token_json(settings.token_json)
    creds, changed = drive_sync.ensure_fresh_credentials(creds)
    if changed:
        settings.token_json = creds.to_json()
        db.commit()
    return creds


@router.get("/settings", response_model=schemas.DriveSettingsOut)
def get_settings(db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    s = _get_settings(db)
    return schemas.DriveSettingsOut(
        folder_link=s.folder_link or "",
        folder_id=s.folder_id or "",
        has_credentials=bool(s.client_config_json),
        has_token=bool(s.token_json),
    )


@router.post("/settings", response_model=schemas.DriveSettingsOut)
def set_settings(payload: schemas.DriveSettingsIn, db: Session = Depends(get_db),
                  admin: models.User = Depends(get_current_admin)):
    if not drive_sync.GOOGLE_LIBS_AVAILABLE:
        raise HTTPException(500, f"Librerías de Google no disponibles: {drive_sync.GOOGLE_LIBS_IMPORT_ERROR}")
    s = _get_settings(db)
    try:
        folder_id = drive_sync.extract_folder_id(payload.folder_link)
    except drive_sync.DriveSyncError as e:
        raise HTTPException(400, str(e))
    s.folder_link = payload.folder_link
    s.folder_id = folder_id

    if payload.client_config_json:
        try:
            parsed = json.loads(payload.client_config_json)
        except json.JSONDecodeError:
            raise HTTPException(400, "El archivo de credenciales no es un JSON válido.")
        if "web" not in parsed:
            raise HTTPException(
                400,
                "Las credenciales deben ser de tipo 'Aplicación web' (deben tener "
                "la clave 'web' en el JSON), no 'Aplicación de escritorio'. Ver README.",
            )
        s.client_config_json = payload.client_config_json
        s.token_json = None  # credenciales nuevas invalidan el token anterior

    db.commit()
    db.refresh(s)
    return schemas.DriveSettingsOut(
        folder_link=s.folder_link or "", folder_id=s.folder_id or "",
        has_credentials=bool(s.client_config_json), has_token=bool(s.token_json),
    )


@router.get("/oauth/start")
def oauth_start(request: Request, db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    if not drive_sync.GOOGLE_LIBS_AVAILABLE:
        raise HTTPException(500, f"Librerías de Google no disponibles: {drive_sync.GOOGLE_LIBS_IMPORT_ERROR}")
    s = _get_settings(db)
    if not s.client_config_json:
        raise HTTPException(400, "Primero sube el archivo de credenciales (credentials.json).")
    client_config = json.loads(s.client_config_json)
    flow = drive_sync.build_flow(client_config, REDIRECT_URI)
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    request.session["drive_oauth_state"] = state
    return RedirectResponse(auth_url)


@router.get("/oauth/callback")
def oauth_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None,
                    error: Optional[str] = None,
                    db: Session = Depends(get_db)):
    if error:
        return RedirectResponse(f"/drive-settings.html?drive_error={error}")
    expected_state = request.session.get("drive_oauth_state")
    if not code or not state or state != expected_state:
        return RedirectResponse("/drive-settings.html?drive_error=estado_invalido")

    s = _get_settings(db)
    client_config = json.loads(s.client_config_json)
    flow = drive_sync.build_flow(client_config, REDIRECT_URI, state=state)
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        return RedirectResponse(f"/drive-settings.html?drive_error={e}")

    s.token_json = flow.credentials.to_json()
    db.commit()
    return RedirectResponse("/drive-settings.html?drive_ok=1")


@router.post("/test")
def test_connection(db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    if not drive_sync.GOOGLE_LIBS_AVAILABLE:
        raise HTTPException(500, f"Librerías de Google no disponibles: {drive_sync.GOOGLE_LIBS_IMPORT_ERROR}")
    s = _get_settings(db)
    if not s.folder_id:
        raise HTTPException(400, "Configura primero el enlace de la carpeta.")
    creds = _get_valid_credentials(db, s)
    service = drive_sync.get_drive_service(creds)
    try:
        name = drive_sync.test_connection(service, s.folder_id)
    except drive_sync.DriveSyncError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "folder_name": name}


def _run_upload_job(folder_id: str, client_config: dict, token_json: str):
    global _upload_job
    db = SessionLocal()
    try:
        creds = drive_sync.credentials_from_token_json(token_json)
        creds, changed = drive_sync.ensure_fresh_credentials(creds)
        if changed:
            s = db.query(models.DriveSettings).first()
            if s:
                s.token_json = creds.to_json()
                db.commit()
        service = drive_sync.get_drive_service(creds)

        images = db.query(models.Image).order_by(models.Image.id).all()
        images_payload = [
            {
                "filename": img.filename,
                "original_filename": img.original_filename,
                "width": img.width,
                "height": img.height,
                "data": img.data or {"points": [], "regions": []},
            }
            for img in images
        ]
        labels = [
            {
                "name": l.name,
                "color": l.color,
                "is_category": l.is_category,
                "parent_id": l.parent_id,
            }
            for l in db.query(models.Label).all()
        ]

        def progress_cb(done, total, name):
            with _upload_lock:
                _upload_job.update(status="running", done=done, total=total, current_name=name)

        def resolver(filename):
            return os.path.join(config.IMAGES_DIR, filename)

        done, total, status = drive_sync.sync_project(
            service, folder_id, images_payload, labels, resolver,
            progress_callback=progress_cb, cancel_event=_upload_cancel_event,
        )
        with _upload_lock:
            _upload_job.update(status=status, done=done, total=total, current_name="", message="")
    except Exception as e:
        with _upload_lock:
            _upload_job.update(status="error", message=str(e))
    finally:
        db.close()


@router.post("/upload")
def start_upload(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if not drive_sync.GOOGLE_LIBS_AVAILABLE:
        raise HTTPException(500, f"Librerías de Google no disponibles: {drive_sync.GOOGLE_LIBS_IMPORT_ERROR}")
    with _upload_lock:
        if _upload_job["status"] == "running":
            raise HTTPException(409, "Ya hay una subida en curso.")

    s = _get_settings(db)
    if not s.folder_id or not s.client_config_json or not s.token_json:
        raise HTTPException(400, "Google Drive no está completamente configurado todavía.")

    _upload_cancel_event.clear()
    with _upload_lock:
        _upload_job.update(status="running", done=0, total=0, current_name="", message="")

    client_config = json.loads(s.client_config_json)
    thread = threading.Thread(
        target=_run_upload_job, args=(s.folder_id, client_config, s.token_json), daemon=True
    )
    thread.start()
    return {"ok": True}


@router.get("/upload/status")
def upload_status(user: models.User = Depends(get_current_user)):
    with _upload_lock:
        return dict(_upload_job)


@router.post("/upload/cancel")
def cancel_upload(user: models.User = Depends(get_current_user)):
    _upload_cancel_event.set()
    return {"ok": True}
