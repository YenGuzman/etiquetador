# -*- coding: utf-8 -*-
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .database import get_db
from . import models


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión inválida")
    return user


def get_current_admin(user: models.User = Depends(get_current_user)) -> models.User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requiere permisos de administrador")
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(models.User).filter(models.User.id == user_id).first()
