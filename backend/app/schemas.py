# -*- coding: utf-8 -*-
from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    is_admin: bool

    class Config:
        from_attributes = True


class UserCreateRequest(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class LabelIn(BaseModel):
    name: str
    color: Optional[str] = None
    parent_id: Optional[int] = None  # si se da, debe ser el id de una categoría


class CategoryIn(BaseModel):
    name: str
    color: Optional[str] = None


class LabelOut(BaseModel):
    id: int
    name: str
    color: str
    is_category: bool
    parent_id: Optional[int] = None

    class Config:
        from_attributes = True


class LabelParentUpdate(BaseModel):
    parent_id: Optional[int] = None


class LabelRename(BaseModel):
    new_name: str


class LabelColor(BaseModel):
    color: str


class ImageSummary(BaseModel):
    id: int
    original_filename: str
    width: int
    height: int
    has_annotations: bool
    locked_by: Optional[str] = None
    locked_seconds_ago: Optional[float] = None

    class Config:
        from_attributes = True


class AnnotationData(BaseModel):
    points: List[Dict[str, Any]] = Field(default_factory=list)
    regions: List[Dict[str, Any]] = Field(default_factory=list)


class DriveSettingsIn(BaseModel):
    folder_link: str
    client_config_json: Optional[str] = None


class DriveSettingsOut(BaseModel):
    folder_link: str
    folder_id: str
    has_credentials: bool
    has_token: bool
