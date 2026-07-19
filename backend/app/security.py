# -*- coding: utf-8 -*-
"""Se usa bcrypt directamente (en vez de passlib) porque las versiones
recientes de passlib tienen un bug de compatibilidad conocido con bcrypt>=4
(AttributeError: module 'bcrypt' has no attribute '__about__')."""

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False
