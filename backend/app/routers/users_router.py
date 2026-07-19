# -*- coding: utf-8 -*-
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, security
from ..database import get_db
from ..auth import get_current_admin

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=List[schemas.UserOut])
def list_users(db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    return db.query(models.User).order_by(models.User.username).all()


@router.post("", response_model=schemas.UserOut)
def create_user(payload: schemas.UserCreateRequest, db: Session = Depends(get_db),
                 admin: models.User = Depends(get_current_admin)):
    if not payload.username.strip() or not payload.password:
        raise HTTPException(400, "Usuario y contraseña son obligatorios.")
    existing = db.query(models.User).filter(models.User.username == payload.username).first()
    if existing:
        raise HTTPException(400, "Ya existe un usuario con ese nombre.")
    user = models.User(
        username=payload.username.strip(),
        password_hash=security.hash_password(payload.password),
        is_admin=payload.is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), admin: models.User = Depends(get_current_admin)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Usuario no encontrado.")
    if user.id == admin.id:
        raise HTTPException(400, "No puedes eliminar tu propia cuenta mientras estás conectado con ella.")
    remaining_admins = db.query(models.User).filter(models.User.is_admin == True, models.User.id != user.id).count()
    if user.is_admin and remaining_admins == 0:
        raise HTTPException(400, "No puedes eliminar el único administrador restante.")
    db.delete(user)
    db.commit()
    return {"ok": True}
