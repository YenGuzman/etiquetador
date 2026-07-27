# -*- coding: utf-8 -*-
import datetime
import io
import json
import os
import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from PIL import Image as PILImage

from .. import models, schemas, config
from ..database import get_db
from ..auth import get_current_user

router = APIRouter(prefix="/api/images", tags=["images"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def _lock_info(image: models.Image, db: Session):
    if not image.locked_by_id or not image.locked_at:
        return None, None
    age = (datetime.datetime.utcnow() - image.locked_at).total_seconds()
    if age > config.LOCK_TIMEOUT_SECONDS:
        return None, None  # expiró, se considera libre
    user = db.query(models.User).filter(models.User.id == image.locked_by_id).first()
    return (user.username if user else "desconocido"), age


def _to_summary(image: models.Image, db: Session) -> schemas.ImageSummary:
    locked_by, age = _lock_info(image, db)
    data = image.data or {"points": [], "regions": []}
    has_ann = bool(data.get("points") or data.get("regions"))
    return schemas.ImageSummary(
        id=image.id,
        original_filename=image.original_filename,
        width=image.width,
        height=image.height,
        has_annotations=has_ann,
        locked_by=locked_by,
        locked_seconds_ago=age,
    )


@router.get("", response_model=List[schemas.ImageSummary])
def list_images(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    images = db.query(models.Image).order_by(models.Image.id).all()
    return [_to_summary(img, db) for img in images]


@router.post("/upload")
async def upload_images(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    created = []
    errors = []
    for f in files:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"{f.filename}: formato no soportado")
            continue
        contents = await f.read()
        if len(contents) > config.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            errors.append(f"{f.filename}: supera el tamaño máximo de {config.MAX_UPLOAD_SIZE_MB} MB")
            continue
        try:
            with PILImage.open(io.BytesIO(contents)) as im:
                im = im.convert("RGB")
                width, height = im.size
                stored_name = f"{uuid.uuid4().hex}{ext}"
                stored_path = os.path.join(config.IMAGES_DIR, stored_name)
                im.save(stored_path, quality=95)
        except Exception as e:
            errors.append(f"{f.filename}: no se pudo procesar ({e})")
            continue

        image = models.Image(
            filename=stored_name,
            original_filename=f.filename,
            width=width,
            height=height,
            data={"points": [], "regions": []},
            uploaded_by_id=user.id,
        )
        db.add(image)
        db.commit()
        db.refresh(image)
        created.append(image.id)

    return {"created": created, "errors": errors}


@router.get("/export")
def export_dataset(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    labels = db.query(models.Label).order_by(models.Label.name).all()
    images = db.query(models.Image).order_by(models.Image.id).all()
    dataset = {
        "categorias": [{"name": l.name, "color": l.color} for l in labels],
        "imagenes": [
            {
                "image": img.original_filename,
                "width": img.width,
                "height": img.height,
                "points": (img.data or {}).get("points", []),
                "regions": (img.data or {}).get("regions", []),
            }
            for img in images
        ],
    }
    payload = json.dumps(dataset, ensure_ascii=False, indent=2).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=dataset_completo.json"},
    )


def _get_image_or_404(image_id: int, db: Session) -> models.Image:
    image = db.query(models.Image).filter(models.Image.id == image_id).first()
    if not image:
        raise HTTPException(404, "Imagen no encontrada.")
    return image


@router.get("/{image_id}/file")
def get_image_file(image_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    image = _get_image_or_404(image_id, db)
    path = os.path.join(config.IMAGES_DIR, image.filename)
    if not os.path.isfile(path):
        raise HTTPException(404, "El archivo de imagen no existe en disco.")
    return FileResponse(path)


@router.get("/{image_id}/annotations", response_model=schemas.AnnotationData)
def get_annotations(image_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    image = _get_image_or_404(image_id, db)
    data = image.data or {"points": [], "regions": []}
    return schemas.AnnotationData(points=data.get("points", []), regions=data.get("regions", []))


@router.put("/{image_id}/annotations", response_model=schemas.AnnotationData)
def save_annotations(
    image_id: int, payload: schemas.AnnotationData,
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user),
):
    image = _get_image_or_404(image_id, db)
    locked_by, age = _lock_info(image, db)
    if locked_by is not None and locked_by != user.username:
        raise HTTPException(409, f"Esta imagen está siendo editada por {locked_by}.")

    image.data = {"points": payload.points, "regions": payload.regions}
    image.updated_by_id = user.id
    db.commit()
    return payload


@router.post("/{image_id}/lock")
def lock_image(image_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    image = _get_image_or_404(image_id, db)
    locked_by, age = _lock_info(image, db)
    if locked_by is not None and locked_by != user.username:
        raise HTTPException(409, detail=f"{locked_by} está editando esta imagen ahora mismo.")
    image.locked_by_id = user.id
    image.locked_at = datetime.datetime.utcnow()
    db.commit()
    return {"ok": True, "timeout_seconds": config.LOCK_TIMEOUT_SECONDS}


@router.post("/{image_id}/heartbeat")
def heartbeat_image(image_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    image = _get_image_or_404(image_id, db)
    locked_by, age = _lock_info(image, db)
    if locked_by is not None and locked_by != user.username:
        raise HTTPException(409, detail=f"{locked_by} está editando esta imagen ahora mismo.")
    image.locked_by_id = user.id
    image.locked_at = datetime.datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.post("/{image_id}/unlock")
def unlock_image(image_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    image = _get_image_or_404(image_id, db)
    if image.locked_by_id == user.id:
        image.locked_by_id = None
        image.locked_at = None
        db.commit()
    return {"ok": True}


@router.delete("/{image_id}")
def delete_image(image_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    image = _get_image_or_404(image_id, db)
    locked_by, age = _lock_info(image, db)
    if locked_by is not None and locked_by != user.username:
        raise HTTPException(409, f"Esta imagen está siendo editada por {locked_by}.")
    path = os.path.join(config.IMAGES_DIR, image.filename)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
    db.delete(image)
    db.commit()
    return {"ok": True}
