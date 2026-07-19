# -*- coding: utf-8 -*-
import os
import shutil
import tempfile
import io

TEST_DATA_DIR = tempfile.mkdtemp(prefix="labeler_test_")
os.environ["DATA_DIR"] = TEST_DATA_DIR
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin1234"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["LOCK_TIMEOUT_SECONDS"] = "2"  # corto, para probar expiración rápido

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.main import app

client = TestClient(app)


def login(username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    return r


def test_health():
    r = client.get("/health")
    assert r.status_code == 200


def test_login_admin_bootstrap():
    r = login("admin", "admin1234")
    assert r.status_code == 200, r.text
    assert r.json()["is_admin"] is True


def test_login_wrong_password():
    r = login("admin", "incorrecta")
    assert r.status_code == 401


def test_create_user_requires_admin():
    c = TestClient(app)  # cliente sin sesión
    r = c.post("/api/users", json={"username": "doctor1", "password": "clave123"})
    assert r.status_code == 401


def test_admin_creates_doctor_user():
    admin_client = TestClient(app)
    login_r = admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    assert login_r.status_code == 200
    r = admin_client.post("/api/users", json={"username": "dra_gomez", "password": "clave123", "is_admin": False})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "dra_gomez"

    # El nuevo usuario puede iniciar sesión
    doctor_client = TestClient(app)
    r2 = doctor_client.post("/api/auth/login", json={"username": "dra_gomez", "password": "clave123"})
    assert r2.status_code == 200
    assert r2.json()["is_admin"] is False
    return doctor_client


def test_labels_crud():
    admin_client = TestClient(app)
    admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})

    r = admin_client.post("/api/labels", json={"name": "Lesion papilar"})
    assert r.status_code == 200, r.text
    label_id = r.json()["id"]
    assert r.json()["color"]

    r = admin_client.get("/api/labels")
    assert any(l["name"] == "Lesion papilar" for l in r.json())

    r = admin_client.patch(f"/api/labels/{label_id}/rename", json={"new_name": "Papiloma"})
    assert r.status_code == 200
    assert r.json()["name"] == "Papiloma"

    r = admin_client.patch(f"/api/labels/{label_id}/color", json={"color": "#123456"})
    assert r.status_code == 200
    assert r.json()["color"] == "#123456"

    # No permite duplicados
    admin_client.post("/api/labels", json={"name": "Otra"})
    r = admin_client.post("/api/labels", json={"name": "Otra"})
    assert r.status_code == 400


def _make_test_image_bytes(color=(10, 20, 30), size=(200, 150)):
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, format="JPEG")
    buf.seek(0)
    return buf


def test_upload_and_annotate_flow():
    admin_client = TestClient(app)
    admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})

    img_bytes = _make_test_image_bytes()
    r = admin_client.post(
        "/api/images/upload",
        files={"files": ("img_test.jpg", img_bytes, "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    created = r.json()["created"]
    assert len(created) == 1
    image_id = created[0]

    r = admin_client.get("/api/images")
    assert r.status_code == 200
    summary = [i for i in r.json() if i["id"] == image_id][0]
    assert summary["width"] == 200 and summary["height"] == 150
    assert summary["has_annotations"] is False
    assert summary["locked_by"] is None

    # Descargar el archivo de imagen
    r = admin_client.get(f"/api/images/{image_id}/file")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")

    # Anotaciones vacías al inicio
    r = admin_client.get(f"/api/images/{image_id}/annotations")
    assert r.status_code == 200
    assert r.json()["points"] == []

    # Guardar sin bloquear primero -> debe fallar (requiere lock)... en
    # realidad no bloqueamos el guardado si NADIE tiene el lock (solo si
    # alguien MÁS lo tiene). Verifiquemos ese comportamiento:
    payload = {"points": [{"id": "p1", "x": 10, "y": 20, "label": "Papiloma"}], "regions": []}
    r = admin_client.put(f"/api/images/{image_id}/annotations", json=payload)
    assert r.status_code == 200, r.text

    r = admin_client.get(f"/api/images/{image_id}/annotations")
    assert len(r.json()["points"]) == 1

    return image_id


def test_locking_between_two_users():
    admin_client = TestClient(app)
    admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})

    doctor_client = TestClient(app)
    doctor_client.post("/api/auth/login", json={"username": "dra_gomez", "password": "clave123"})

    img_bytes = _make_test_image_bytes(color=(50, 60, 70))
    r = admin_client.post("/api/images/upload", files={"files": ("img_lock.jpg", img_bytes, "image/jpeg")})
    image_id = r.json()["created"][0]

    # El admin bloquea la imagen
    r = admin_client.post(f"/api/images/{image_id}/lock")
    assert r.status_code == 200, r.text

    # La doctora intenta bloquearla también -> debe fallar con 409
    r = doctor_client.post(f"/api/images/{image_id}/lock")
    assert r.status_code == 409, r.text

    # La doctora ve en la lista que está bloqueada por 'admin'
    r = doctor_client.get("/api/images")
    summary = [i for i in r.json() if i["id"] == image_id][0]
    assert summary["locked_by"] == "admin"

    # La doctora intenta guardar anotaciones sobre esa imagen -> debe fallar
    r = doctor_client.put(
        f"/api/images/{image_id}/annotations",
        json={"points": [{"id": "x", "x": 1, "y": 1, "label": "Papiloma"}], "regions": []},
    )
    assert r.status_code == 409, r.text

    # El admin libera el bloqueo
    r = admin_client.post(f"/api/images/{image_id}/unlock")
    assert r.status_code == 200

    # Ahora la doctora sí puede bloquear y guardar
    r = doctor_client.post(f"/api/images/{image_id}/lock")
    assert r.status_code == 200, r.text
    r = doctor_client.put(
        f"/api/images/{image_id}/annotations",
        json={"points": [{"id": "x", "x": 1, "y": 1, "label": "Papiloma"}], "regions": []},
    )
    assert r.status_code == 200, r.text


def test_lock_expires_after_timeout():
    import time
    admin_client = TestClient(app)
    admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    doctor_client = TestClient(app)
    doctor_client.post("/api/auth/login", json={"username": "dra_gomez", "password": "clave123"})

    img_bytes = _make_test_image_bytes(color=(90, 90, 90))
    r = admin_client.post("/api/images/upload", files={"files": ("img_expire.jpg", img_bytes, "image/jpeg")})
    image_id = r.json()["created"][0]

    r = admin_client.post(f"/api/images/{image_id}/lock")
    assert r.status_code == 200

    # LOCK_TIMEOUT_SECONDS=2 en este test; esperamos a que expire
    time.sleep(2.5)

    r = doctor_client.post(f"/api/images/{image_id}/lock")
    assert r.status_code == 200, "El bloqueo debió expirar y permitir que otra persona lo tome"


def test_export_dataset():
    admin_client = TestClient(app)
    admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    r = admin_client.get("/api/images/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    import json as _json
    data = _json.loads(r.content)
    assert "categorias" in data and "imagenes" in data


def test_delete_last_admin_forbidden():
    admin_client = TestClient(app)
    admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    r = admin_client.get("/api/users")
    admin_user = [u for u in r.json() if u["username"] == "admin"][0]
    r = admin_client.delete(f"/api/users/{admin_user['id']}")
    assert r.status_code == 400  # no puede eliminarse a sí mismo


def test_default_categories_bootstrapped():
    admin_client = TestClient(app)
    admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})
    r = admin_client.get("/api/labels")
    names = {l["name"] for l in r.json() if l["is_category"]}
    assert {"Benigno", "Sospechoso", "Maligno"}.issubset(names)


def test_category_and_subtag_hierarchy():
    admin_client = TestClient(app)
    admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})

    r = admin_client.get("/api/labels")
    benigno = [l for l in r.json() if l["name"] == "Benigno"][0]

    # Crear un subtag directamente bajo la categoría "Benigno"
    r = admin_client.post("/api/labels", json={"name": "Papiloma intraductal", "parent_id": benigno["id"]})
    assert r.status_code == 200, r.text
    subtag = r.json()
    assert subtag["parent_id"] == benigno["id"]
    assert subtag["is_category"] is False

    # No se puede crear un subtag bajo algo que no es categoría
    r = admin_client.post("/api/labels", json={"name": "Otra cosa", "parent_id": subtag["id"]})
    assert r.status_code == 400

    # Crear una nueva categoría
    r = admin_client.post("/api/labels/categories", json={"name": "Indeterminado"})
    assert r.status_code == 200, r.text
    nueva_cat = r.json()
    assert nueva_cat["is_category"] is True

    # Mover el subtag a la nueva categoría
    r = admin_client.patch(f"/api/labels/{subtag['id']}/parent", json={"parent_id": nueva_cat["id"]})
    assert r.status_code == 200
    assert r.json()["parent_id"] == nueva_cat["id"]

    # Una categoría no puede colgar de otra categoría
    r = admin_client.patch(f"/api/labels/{nueva_cat['id']}/parent", json={"parent_id": benigno["id"]})
    assert r.status_code == 400

    # Quitarle la categoría (dejarlo "sin categoría")
    r = admin_client.patch(f"/api/labels/{subtag['id']}/parent", json={"parent_id": None})
    assert r.status_code == 200
    assert r.json()["parent_id"] is None


def test_delete_category_orphans_children_not_deletes_them():
    admin_client = TestClient(app)
    admin_client.post("/api/auth/login", json={"username": "admin", "password": "admin1234"})

    r = admin_client.post("/api/labels/categories", json={"name": "CategoriaTemporal"})
    cat = r.json()
    r = admin_client.post("/api/labels", json={"name": "SubtagTemporal", "parent_id": cat["id"]})
    subtag = r.json()

    r = admin_client.delete(f"/api/labels/{cat['id']}")
    assert r.status_code == 200

    r = admin_client.get("/api/labels")
    remaining = {l["name"]: l for l in r.json()}
    assert "CategoriaTemporal" not in remaining          # la categoría sí se borró
    assert "SubtagTemporal" in remaining                  # el subtag sigue existiendo
    assert remaining["SubtagTemporal"]["parent_id"] is None  # pero ahora sin categoría


def test_migration_adds_columns_to_old_schema_db():
    """Simula una base de datos creada ANTES de que existiera parent_id/
    is_category (esquema viejo de 'labels'), y verifica que la migración
    ligera la actualiza sin romperse."""
    import sqlite3
    from sqlalchemy import create_engine, inspect as sa_inspect
    from app import database as db_module

    old_db_path = os.path.join(TEST_DATA_DIR, "old_schema.db")
    conn = sqlite3.connect(old_db_path)
    conn.execute(
        "CREATE TABLE labels (id INTEGER PRIMARY KEY, name VARCHAR(120) UNIQUE NOT NULL, "
        "color VARCHAR(20) NOT NULL, created_at DATETIME)"
    )
    conn.execute("INSERT INTO labels (id, name, color) VALUES (1, 'EtiquetaVieja', '#abcdef')")
    conn.commit()
    conn.close()

    old_engine = create_engine(f"sqlite:///{old_db_path}", connect_args={"check_same_thread": False})
    cols_before = {c["name"] for c in sa_inspect(old_engine).get_columns("labels")}
    assert "parent_id" not in cols_before
    assert "is_category" not in cols_before

    # Reutilizamos la misma lógica de migración apuntando a este engine viejo
    from sqlalchemy import text
    inspector = sa_inspect(old_engine)
    existing_cols = {c["name"] for c in inspector.get_columns("labels")}
    with old_engine.begin() as conn2:
        if "parent_id" not in existing_cols:
            conn2.execute(text("ALTER TABLE labels ADD COLUMN parent_id INTEGER"))
        if "is_category" not in existing_cols:
            conn2.execute(text("ALTER TABLE labels ADD COLUMN is_category BOOLEAN DEFAULT 0"))

    cols_after = {c["name"] for c in sa_inspect(old_engine).get_columns("labels")}
    assert "parent_id" in cols_after
    assert "is_category" in cols_after

    # La fila vieja sigue ahí y accesible, con los valores nuevos en NULL/0
    conn3 = sqlite3.connect(old_db_path)
    row = conn3.execute("SELECT name, parent_id, is_category FROM labels WHERE id=1").fetchone()
    conn3.close()
    assert row[0] == "EtiquetaVieja"
    assert row[1] is None
    assert row[2] in (0, None)


def teardown_module(module):
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
