# -*- coding: utf-8 -*-
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..auth import get_current_user, get_current_admin

router = APIRouter(prefix="/api/labels", tags=["labels"])

DEFAULT_PALETTE = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#46f0f0", "#f032e6", "#bcf60c", "#fabebe", "#008080",
    "#e6beff", "#9a6324", "#800000", "#aaffc3", "#808000",
    "#ffd8b1", "#000075", "#808080", "#ffe119", "#000000",
]


def _next_color(db: Session) -> str:
    used = {l.color for l in db.query(models.Label).all()}
    for c in DEFAULT_PALETTE:
        if c not in used:
            return c
    count = db.query(models.Label).count()
    return DEFAULT_PALETTE[count % len(DEFAULT_PALETTE)]


def _propagate_rename(db: Session, old_name: str, new_name: str, category_name: str = ""):
    for image in db.query(models.Image).all():
        changed = False
        data = image.data or {"points": [], "regions": []}
        for collection in (data.get("points", []), data.get("regions", [])):
            for annotation in collection:
                if annotation.get("label") != old_name:
                    continue
                # Las anotaciones antiguas no tienen categoría: se mantienen
                # compatibles y se renombran por nombre. Las nuevas se
                # limitan a su categoría para soportar subtags homónimos.
                if category_name and annotation.get("category", "") not in ("", category_name):
                    continue
                annotation["label"] = new_name
                changed = True
        if changed:
            image.data = data
    db.commit()


@router.get("", response_model=List[schemas.LabelOut])
def list_labels(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return db.query(models.Label).order_by(models.Label.is_category.desc(), models.Label.name).all()


@router.post("/categories", response_model=schemas.LabelOut)
def create_category(payload: schemas.CategoryIn, db: Session = Depends(get_db),
                     user: models.User = Depends(get_current_admin)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "El nombre de la categoría no puede estar vacío.")
    if db.query(models.Label).filter(models.Label.name == name).first():
        raise HTTPException(400, "Ya existe una etiqueta o categoría con ese nombre.")
    color = payload.color or _next_color(db)
    category = models.Label(name=name, color=color, is_category=True, parent_id=None)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@router.post("", response_model=schemas.LabelOut)
def create_label(payload: schemas.LabelIn, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_admin)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(400, "El nombre de la etiqueta no puede estar vacío.")
    parent_id = payload.parent_id
    if parent_id is not None:
        parent = db.query(models.Label).filter(models.Label.id == parent_id).first()
        if not parent:
            raise HTTPException(404, "La categoría indicada no existe.")
        if not parent.is_category:
            raise HTTPException(400, "El elemento indicado como categoría no es una categoría.")

        # El mismo subtag puede existir bajo categorías distintas, pero no
        # puede repetirse dentro de la misma categoría.
        duplicate = (db.query(models.Label)
            .filter(models.Label.name == name, models.Label.parent_id == parent_id,
                    models.Label.is_category == False)
            .first())
        if duplicate:
            raise HTTPException(400, f"Ya existe el subtag '{name}' dentro de la categoría indicada.")
    else:
        # Los subtags sin categoría también deben tener nombres únicos entre
        # sí para evitar ambigüedad mientras permanezcan sin categoría.
        duplicate = (db.query(models.Label)
            .filter(models.Label.name == name, models.Label.parent_id.is_(None),
                    models.Label.is_category == False)
            .first())
        if duplicate:
            raise HTTPException(400, f"Ya existe un subtag sin categoría llamado '{name}'.")

    color = payload.color or _next_color(db)
    label = models.Label(name=name, color=color, is_category=False, parent_id=parent_id)
    db.add(label)
    db.commit()
    db.refresh(label)
    return label


@router.patch("/{label_id}/parent", response_model=schemas.LabelOut)
def set_label_parent(label_id: int, payload: schemas.LabelParentUpdate, db: Session = Depends(get_db),
                      user: models.User = Depends(get_current_admin)):
    label = db.query(models.Label).filter(models.Label.id == label_id).first()
    if not label:
        raise HTTPException(404, "Etiqueta no encontrada.")
    if label.is_category:
        raise HTTPException(400, "Una categoría no puede moverse debajo de otra categoría.")

    if label.parent_id is not None and payload.parent_id != label.parent_id:
        raise HTTPException(400,
            "Este subtag ya pertenece a una categoría y no puede cambiarse de categoría. Solo los subtags sin categoría pueden asignarse a un maintag.")

    if payload.parent_id is not None:
        parent = db.query(models.Label).filter(models.Label.id == payload.parent_id).first()
        if not parent:
            raise HTTPException(404, "La categoría indicada no existe.")
        if not parent.is_category:
            raise HTTPException(400, "El elemento indicado como categoría no es una categoría.")

        duplicate = (db.query(models.Label)
            .filter(models.Label.id != label.id, models.Label.name == label.name,
                    models.Label.parent_id == payload.parent_id,
                    models.Label.is_category == False)
            .first())
        if duplicate:
            raise HTTPException(400,
                f"No se puede asignar el subtag '{label.name}' a esa categoría porque ya existe otro subtag con el mismo nombre dentro de ella.")

    label.parent_id = payload.parent_id
    db.commit()
    db.refresh(label)
    return label


@router.patch("/{label_id}/rename", response_model=schemas.LabelOut)
def rename_label(label_id: int, payload: schemas.LabelRename, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_admin)):
    label = db.query(models.Label).filter(models.Label.id == label_id).first()
    if not label:
        raise HTTPException(404, "Etiqueta no encontrada.")
    new_name = payload.new_name.strip()
    if not new_name:
        raise HTTPException(400, "El nombre no puede estar vacío.")
    if new_name != label.name:
        if label.is_category:
            duplicate = (db.query(models.Label)
                .filter(models.Label.id != label.id, models.Label.is_category == True,
                        models.Label.name == new_name).first())
        else:
            duplicate = (db.query(models.Label)
                .filter(models.Label.id != label.id, models.Label.is_category == False,
                        models.Label.name == new_name, models.Label.parent_id == label.parent_id).first())
        if duplicate:
            raise HTTPException(400, "Ya existe una etiqueta con ese nombre dentro del mismo nivel/categoría.")

    old_name = label.name
    category_name = ""
    if not label.is_category and label.parent_id:
        parent = db.query(models.Label).filter(models.Label.id == label.parent_id).first()
        category_name = parent.name if parent else ""
    label.name = new_name
    db.commit()

    if not label.is_category:
        _propagate_rename(db, old_name, new_name, category_name)

    db.refresh(label)
    return label


@router.patch("/{label_id}/color", response_model=schemas.LabelOut)
def set_label_color(label_id: int, payload: schemas.LabelColor, db: Session = Depends(get_db),
                     user: models.User = Depends(get_current_admin)):
    label = db.query(models.Label).filter(models.Label.id == label_id).first()
    if not label:
        raise HTTPException(404, "Etiqueta no encontrada.")
    label.color = payload.color
    db.commit()
    db.refresh(label)
    return label


@router.delete("/{label_id}")
def delete_label(label_id: int, db: Session = Depends(get_db),
                  user: models.User = Depends(get_current_admin)):
    label = db.query(models.Label).filter(models.Label.id == label_id).first()
    if not label:
        raise HTTPException(404, "Etiqueta no encontrada.")

    if label.is_category:
        # No borramos en cascada los subtags (podrían tener anotaciones ya
        # hechas); simplemente quedan "sin categoría".
        children = db.query(models.Label).filter(models.Label.parent_id == label.id).all()
        for child in children:
            child.parent_id = None
        db.commit()

    db.delete(label)
    db.commit()
    return {"ok": True}
