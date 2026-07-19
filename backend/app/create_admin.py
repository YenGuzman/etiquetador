# -*- coding: utf-8 -*-
"""Crea (o actualiza la contraseña de) un usuario administrador.

Uso:
    python -m app.create_admin
"""
import getpass

from .database import SessionLocal, Base, engine
from . import models, security

Base.metadata.create_all(bind=engine)


def main():
    username = input("Nombre de usuario del administrador: ").strip()
    if not username:
        print("El nombre de usuario no puede estar vacío.")
        return
    password = getpass.getpass("Contraseña: ")
    if len(password) < 4:
        print("La contraseña es muy corta.")
        return

    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == username).first()
        if user:
            user.password_hash = security.hash_password(password)
            user.is_admin = True
            db.commit()
            print(f"Contraseña actualizada para el administrador existente '{username}'.")
        else:
            user = models.User(
                username=username,
                password_hash=security.hash_password(password),
                is_admin=True,
            )
            db.add(user)
            db.commit()
            print(f"Administrador '{username}' creado correctamente.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
