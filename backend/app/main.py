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
    """
    Crea las categorias y subtags predeterminados si todavia no existen.

    Las categorias generales tienen is_category=True y parent_id=None.
    Los subtags tienen is_category=False y parent_id apuntando a su categoria.

    No duplica categorias ni subtags existentes.
    """
    db = SessionLocal()

    try:
        # Categorias y sus respectivos subtags.
        defaults = {
            "Atipicas/Precursora": [
                "Hiperplasia Ductal Atipica en papiloma",
                "Hiperplasia ductal atipica",
            ],
            "Neoplasia Benigna": [
                "Adenoma Ductal",
                "Papiloma Esclerosado",
                "Papiloma intraductal",
            ],
            "Neoplasia Maligna": [
                "Carcinoma Ductal in situ Comedo",
                "Carcinoma Ductal in situ Cribiforme",
                "Carcinoma Ductal in situ Micropapilar",
                "Carcinoma Ductal in situ Papilar",
                "Carcinoma Ductal in situ solido",
                "Carcinoma ductal in situ en papiloma",
                "Carcinoma papilar encapsulado",
                "Carcinoma papilar solido in situ",
            ],
            "No neoplasicas": [
                "Ectasia Ductal",
                "Hiperplasia apocrina / Papilar apocrina",
                "Hiperplasia intraductal usual",
                "Metaplasia escamosa",
            ],
        }

        # Colores para las categorias generales.
        category_colors = {
            "Atipicas/Precursora": "#3cb44b",
            "Neoplasia Benigna": "#3cb44b",
            "Neoplasia Maligna": "#3cb44b",
            "No neoplasicas": "#3cb44b",
        }

        # Crear o recuperar las categorias.
        categories = {}

        for category_name, subtags in defaults.items():
            category = (
                db.query(models.Label)
                .filter(
                    models.Label.name == category_name,
                    models.Label.is_category.is_(True),
                    models.Label.parent_id.is_(None),
                )
                .first()
            )

            if category is None:
                category = models.Label(
                    name=category_name,
                    color=category_colors[category_name],
                    is_category=True,
                    parent_id=None,
                )
                db.add(category)
                db.flush()

            categories[category_name] = category

        # Crear los subtags asociados a cada categoria.
        for category_name, subtags in defaults.items():
            category = categories[category_name]

            for subtag_name in subtags:
                existing = (
                    db.query(models.Label)
                    .filter(
                        models.Label.name == subtag_name,
                        models.Label.is_category.is_(False),
                        models.Label.parent_id == category.id,
                    )
                    .first()
                )

                if existing is None:
                    db.add(
                        models.Label(
                            name=subtag_name,
                            color="#3cb44b",
                            is_category=False,
                            parent_id=category.id,
                        )
                    )

        db.commit()

        print(
            "[bootstrap] Categorias y subtags predeterminados "
            "creados o verificados correctamente."
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()



bootstrap_admin()
bootstrap_default_categories()

app = FastAPI(title="Etiquetador de Lesiones Intraductales (Web)")

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

# Sirve los archivos estáticos del frontend (HTML/CSS/JS) bajo la raiz,
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
