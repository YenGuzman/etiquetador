# -*- coding: utf-8 -*-
"""
drive_sync.py (versión web)

A diferencia de la versión de escritorio, aquí:
 - La autorización usa el flujo OAuth "web" (redirect a Google y de vuelta a
   nuestro servidor), no una ventana de navegador local.
 - Las credenciales/token se guardan como texto JSON en la base de datos
   (una sola configuración compartida por todo el servidor, la administra
   el usuario admin), no como archivos en disco.
 - Las imágenes se leen de disco (config.IMAGES_DIR) pero las anotaciones
   viven en la base de datos, así que el JSON de cada imagen se genera en
   memoria al momento de subir, sin necesidad de archivos temporales.
"""

import io
import json
import re
from typing import Optional, Callable, List, Tuple

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
    from googleapiclient.errors import HttpError
    GOOGLE_LIBS_AVAILABLE = True
    GOOGLE_LIBS_IMPORT_ERROR = None
except ImportError as e:
    GOOGLE_LIBS_AVAILABLE = False
    GOOGLE_LIBS_IMPORT_ERROR = str(e)

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"


class DriveSyncError(Exception):
    pass


def extract_folder_id(link_or_id: str) -> str:
    link_or_id = (link_or_id or "").strip()
    if not link_or_id:
        raise DriveSyncError("Debes ingresar un enlace o ID de carpeta de Google Drive.")
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", link_or_id)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", link_or_id)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", link_or_id):
        return link_or_id
    raise DriveSyncError(
        "No se pudo reconocer un ID de carpeta válido en ese enlace. "
        "Copia el enlace de 'Compartir' de la carpeta de Google Drive."
    )


def build_flow(client_config: dict, redirect_uri: str, state: Optional[str] = None) -> "Flow":
    """Construye el objeto Flow de OAuth para el tipo de credencial 'Aplicación
    web'. client_config es el contenido ya parseado del credentials.json
    descargado de Google Cloud Console (debe tener la clave 'web', no
    'installed' — ver instrucciones de configuración)."""
    if "web" not in client_config and "installed" in client_config:
        raise DriveSyncError(
            "Las credenciales son de tipo 'Aplicación de escritorio'. Para el "
            "despliegue web necesitas crear un ID de cliente OAuth de tipo "
            "'Aplicación web' en Google Cloud Console (ver README)."
        )
    return Flow.from_client_config(
        client_config, scopes=SCOPES, redirect_uri=redirect_uri, state=state
    )


def credentials_from_token_json(token_json: str) -> "Credentials":
    info = json.loads(token_json)
    return Credentials.from_authorized_user_info(info, SCOPES)


def ensure_fresh_credentials(creds: "Credentials") -> Tuple["Credentials", bool]:
    """Refresca el token si está vencido. Devuelve (creds, cambiaron)."""
    changed = False
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        changed = True
    return creds, changed


def get_drive_service(creds: "Credentials"):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def test_connection(service, folder_id: str) -> str:
    try:
        meta = service.files().get(
            fileId=folder_id, fields="id, name, mimeType", supportsAllDrives=True
        ).execute()
    except HttpError as e:
        status = getattr(e.resp, "status", None)
        if status == 404:
            raise DriveSyncError(
                "No se encontró esa carpeta, o la cuenta con la que se autorizó "
                "no tiene acceso a ella."
            )
        raise DriveSyncError(f"Error al consultar Google Drive: {e}")
    except Exception as e:
        raise DriveSyncError(f"Error al consultar Google Drive: {e}")

    if meta.get("mimeType") != FOLDER_MIME:
        raise DriveSyncError("El enlace no corresponde a una carpeta de Google Drive.")
    return meta.get("name", "(sin nombre)")


def _escape(name: str) -> str:
    return name.replace("'", "\\'")


def find_or_create_subfolder(service, parent_id: str, name: str) -> str:
    query = (
        f"'{parent_id}' in parents and name = '{_escape(name)}' "
        f"and mimeType = '{FOLDER_MIME}' and trashed = false"
    )
    resp = service.files().list(
        q=query, fields="files(id, name)", supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    files = resp.get("files", [])
    if files:
        return files[0]["id"]
    metadata = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
    created = service.files().create(body=metadata, fields="id", supportsAllDrives=True).execute()
    return created["id"]


def _find_existing(service, parent_id: str, name: str) -> Optional[str]:
    query = f"'{parent_id}' in parents and name = '{_escape(name)}' and trashed = false"
    resp = service.files().list(
        q=query, fields="files(id, name)", supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    existing = resp.get("files", [])
    return existing[0]["id"] if existing else None


def upload_file_from_disk(service, local_path: str, parent_id: str, remote_name: str) -> str:
    existing_id = _find_existing(service, parent_id, remote_name)
    media = MediaFileUpload(local_path, resumable=True)
    if existing_id:
        service.files().update(fileId=existing_id, media_body=media, supportsAllDrives=True).execute()
        return "actualizado"
    metadata = {"name": remote_name, "parents": [parent_id]}
    service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
    return "creado"


def upload_json_bytes(service, content: bytes, parent_id: str, remote_name: str) -> str:
    existing_id = _find_existing(service, parent_id, remote_name)
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype="application/json", resumable=True)
    if existing_id:
        service.files().update(fileId=existing_id, media_body=media, supportsAllDrives=True).execute()
        return "actualizado"
    metadata = {"name": remote_name, "parents": [parent_id]}
    service.files().create(body=metadata, media_body=media, fields="id", supportsAllDrives=True).execute()
    return "creado"


def sync_project(
    service,
    root_folder_id: str,
    images: List[dict],
    labels: List[dict],
    images_dir_resolver: Callable[[str], str],
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_event=None,
) -> Tuple[int, int, str]:
    """
    images: lista de dicts {"filename": <nombre en disco>, "original_filename":
            <nombre a mostrar>, "width", "height", "data": {"points":.., "regions":..}}
    labels: lista de dicts {"name", "color", "is_category", "parent_id"}
    images_dir_resolver(filename) -> ruta absoluta en disco de esa imagen.

    Sube cada imagen a <carpeta>/imagenes/<original_filename>, y un JSON de
    anotaciones por imagen + labels.json a <carpeta>/_annotations/.
    Devuelve (n_procesados, n_total, estado) donde estado es
    "completado" o "cancelado".
    """
    images_folder_id = find_or_create_subfolder(service, root_folder_id, "imagenes")
    annotations_folder_id = find_or_create_subfolder(service, root_folder_id, "_annotations")

    total = len(images) * 2 + 1  # imagen + json por cada una, + labels.json
    done = 0

    for img in images:
        if cancel_event is not None and cancel_event.is_set():
            return done, total, "cancelado"
        if progress_callback:
            progress_callback(done, total, img["original_filename"])
        local_path = images_dir_resolver(img["filename"])
        upload_file_from_disk(service, local_path, images_folder_id, img["original_filename"])
        done += 1

        if cancel_event is not None and cancel_event.is_set():
            return done, total, "cancelado"
        base = img["original_filename"].rsplit(".", 1)[0]
        ann_name = f"{base}.json"
        if progress_callback:
            progress_callback(done, total, ann_name)
        payload = json.dumps(
            {
                "image": img["original_filename"],
                "width": img["width"],
                "height": img["height"],
                "points": img["data"].get("points", []),
                "regions": img["data"].get("regions", []),
            },
            ensure_ascii=False, indent=2,
        ).encode("utf-8")
        upload_json_bytes(service, payload, annotations_folder_id, ann_name)
        done += 1

    if progress_callback:
        progress_callback(done, total, "labels.json")
    labels_payload = json.dumps(labels, ensure_ascii=False, indent=2).encode("utf-8")
    upload_json_bytes(service, labels_payload, annotations_folder_id, "labels.json")
    done += 1

    if progress_callback:
        progress_callback(done, total, "")

    return done, total, "completado"
