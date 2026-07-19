# -*- coding: utf-8 -*-
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from . import config

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()



def _remove_legacy_label_name_unique_constraint():
    """SQLite conserva la restricción UNIQUE de versiones antiguas.
    Reconstruye labels una sola vez para permitir el mismo subtag en
    categorías diferentes."""
    if engine.url.get_backend_name() != "sqlite":
        return
    inspector = inspect(engine)
    if "labels" not in inspector.get_table_names():
        return
    unique_constraints = inspector.get_unique_constraints("labels")
    indexes = inspector.get_indexes("labels")
    has_name_unique = any(c.get("column_names") == ["name"] for c in unique_constraints) or any(
        i.get("unique") and i.get("column_names") == ["name"] for i in indexes
    )
    if not has_name_unique:
        return

    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        conn.execute(text("""
            CREATE TABLE labels_new (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                color VARCHAR(20) NOT NULL,
                created_at DATETIME,
                is_category BOOLEAN NOT NULL DEFAULT 0,
                parent_id INTEGER,
                FOREIGN KEY(parent_id) REFERENCES labels_new(id)
            )
        """))
        conn.execute(text("""
            INSERT INTO labels_new (id, name, color, created_at, is_category, parent_id)
            SELECT id, name, color, created_at, COALESCE(is_category, 0), parent_id
            FROM labels
        """))
        conn.execute(text("DROP TABLE labels"))
        conn.execute(text("ALTER TABLE labels_new RENAME TO labels"))
        conn.execute(text("PRAGMA foreign_keys=ON"))


def run_light_migrations():
    """Agrega columnas nuevas a tablas que ya existían de antes de este
    cambio (SQLAlchemy's create_all no altera tablas existentes, solo crea
    las que faltan). Es idempotente: seguro de correr en cada arranque."""
    inspector = inspect(engine)
    if "labels" not in inspector.get_table_names():
        return  # tabla nueva, create_all ya la crea con el esquema completo
    existing_cols = {c["name"] for c in inspector.get_columns("labels")}
    with engine.begin() as conn:
        if "parent_id" not in existing_cols:
            conn.execute(text("ALTER TABLE labels ADD COLUMN parent_id INTEGER"))
        if "is_category" not in existing_cols:
            conn.execute(text("ALTER TABLE labels ADD COLUMN is_category BOOLEAN DEFAULT 0"))
    _remove_legacy_label_name_unique_constraint()

