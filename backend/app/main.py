# -*- coding: utf-8 -*-
import os

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware

from . import config, models, security
from .database import engine, Base, SessionLocal, run_light_migrations
from .routers import auth_router, users_router, labels_router, images_router, drive_router

Base.metadata.create_all(bind=engine)
run_light_migrations()


def bootstrap_admin():
    """Si no existe ningún usuario y las variables de entorno
    ADMIN_USERNAME/ADMIN_PASSWORD están definidas, crea el primer admin."""
    db = SessionLocal()
    try:
        if db.query(models.User).count() == 0:
            if config.ADMIN_BOOTSTRAP_USERNAME and config.ADMIN_BOOTSTRAP_PASSWORD:
                admin = models.User(
                    username=config.ADMIN_BOOTSTRAP_USERNAME,
                    password_hash=security.hash_password(config.ADMIN_BOOTSTRAP_PASSWORD),
                    is_admin=True,
                )
                db.add(admin)
                db.commit()
                print(f"[bootstrap] Usuario administrador '{admin.username}' creado.")
            else:
                print(
                    "[bootstrap] No hay usuarios y no se definieron ADMIN_USERNAME/"
                    "ADMIN_PASSWORD. Crea un admin con: python -m app.create_admin"
                )
    finally:
        db.close()


def bootstrap_default_categories():
    """Crea las categorías generales Benigno/Maligno/Sospechoso la primera
    vez que arranca la app (si todavía no existe ninguna categoría). Las
    etiquetas ya creadas antes de este cambio quedan disponibles como
    subtags "sin categoría" y se pueden reasignar luego desde el gestor de
    etiquetas."""
    db = SessionLocal()
    try:
        has_category = db.query(models.Label).filter(models.Label.is_category == True).first()
        if has_category:
            return
        defaults = [
            ("Benigno", "#3cb44b"),
            ("Sospechoso", "#f58231"),
            ("Maligno", "#e6194b"),
        ]
        for name, color in defaults:
            existing = db.query(models.Label).filter(models.Label.name == name).first()
            if existing:
                # Ya existía una etiqueta plana con ese nombre (poco probable,
                # pero por si acaso no la duplicamos ni la convertimos sola).
                continue
            db.add(models.Label(name=name, color=color, is_category=True, parent_id=None))
        db.commit()
        print("[bootstrap] Categorías por defecto creadas: Benigno, Sospechoso, Maligno.")
    finally:
        db.close()


bootstrap_admin()
bootstrap_default_categories()

app = FastAPI(title="Etiquetador de Lesiones Papilares (Web)")

app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    same_site="lax",
    https_only=config.SESSION_HTTPS_ONLY,
)

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(labels_router.router)
app.include_router(images_router.router)
app.include_router(drive_router.router)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# Sirve los archivos estáticos del frontend (HTML/CSS/JS) bajo la raíz,
# pero dejando pasar primero /api/* (definido arriba) hacia los routers.
app.mount("/static", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="static")


@app.get("/")
def serve_index():
    return FileResponse(os.path.join(STATIC_DIR, "login.html"))


@app.get("/app.html")
def serve_app():
    return FileResponse(os.path.join(STATIC_DIR, "app.html"))


@app.get("/drive-settings.html")
def serve_drive_settings():
    return FileResponse(os.path.join(STATIC_DIR, "drive-settings.html"))


@app.get("/admin.html")
def serve_admin():
    return FileResponse(os.path.join(STATIC_DIR, "admin.html"))


@app.get("/health")
def health():
    return {"status": "ok"}
