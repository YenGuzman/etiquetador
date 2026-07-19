# -*- coding: utf-8 -*-
import datetime

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, Text
)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow():
    return datetime.datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    password_hash = Column(String(200), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class Label(Base):
    __tablename__ = "labels"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    color = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=utcnow)

    # Jerarquía de dos niveles: categorías generales (is_category=True,
    # parent_id=None) como "Benigno"/"Maligno"/"Sospechoso", y subtags
    # (is_category=False) que cuelgan de una categoría mediante parent_id.
    # Un subtag sin parent_id todavía es válido ("sin categoría"), para no
    # romper etiquetas creadas antes de que existiera esta función.
    is_category = Column(Boolean, default=False, nullable=False)
    parent_id = Column(Integer, ForeignKey("labels.id"), nullable=True)


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True)
    filename = Column(String(300), unique=True, nullable=False)  # nombre en disco
    original_filename = Column(String(300), nullable=False)
    width = Column(Integer, nullable=False)
    height = Column(Integer, nullable=False)

    # Anotaciones guardadas como JSON, con el mismo esquema que ya usaba la
    # app de escritorio: {"points": [...], "regions": [...]}
    data = Column(JSON, nullable=False, default=lambda: {"points": [], "regions": []})

    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Bloqueo cooperativo para edición simultánea
    locked_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    locked_at = Column(DateTime, nullable=True)

    uploaded_by = relationship("User", foreign_keys=[uploaded_by_id])
    updated_by = relationship("User", foreign_keys=[updated_by_id])
    locked_by = relationship("User", foreign_keys=[locked_by_id])


class DriveSettings(Base):
    """Fila única con la configuración de Google Drive del servidor
    (compartida por todos los usuarios, la administra el admin)."""
    __tablename__ = "drive_settings"

    id = Column(Integer, primary_key=True)
    folder_link = Column(String(500), default="")
    folder_id = Column(String(200), default="")
    client_config_json = Column(Text, default="")  # contenido de credentials.json (Web app)
    token_json = Column(Text, nullable=True)        # token OAuth obtenido tras autorizar
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
