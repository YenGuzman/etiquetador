# -*- coding: utf-8 -*-
"""Configuración central: rutas de datos, clave de sesión, etc.
Todo configurable por variables de entorno para facilitar el despliegue."""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Carpeta persistente donde viven la base de datos y las imágenes subidas.
# En despliegue con Docker, esto debe apuntar a un volumen montado.
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "..", "data"))
IMAGES_DIR = os.path.join(DATA_DIR, "images")
DB_PATH = os.path.join(DATA_DIR, "app.db")

os.makedirs(IMAGES_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_PATH}"

# Clave usada para firmar las cookies de sesión. En producción, definir
# SECRET_KEY como variable de entorno con un valor largo y aleatorio.
SECRET_KEY = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion-por-una-aleatoria-larga")

# Cuánto tiempo (segundos) se considera "activo" un bloqueo de imagen sin
# recibir una señal de latido (heartbeat) del cliente antes de liberarse.
LOCK_TIMEOUT_SECONDS = int(os.environ.get("LOCK_TIMEOUT_SECONDS", "60"))

# Bootstrap de administrador inicial (opcional, vía variables de entorno).
# Si no existe ningún usuario en la base de datos al arrancar, y estas dos
# variables están definidas, se crea automáticamente un usuario admin.
ADMIN_BOOTSTRAP_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_BOOTSTRAP_PASSWORD = os.environ.get("ADMIN_PASSWORD")

MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "25"))

# URL pública real de la app (usada para el redirect_uri de Google OAuth).
# Se le quita la barra final para evitar dobles barras al concatenar rutas.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# Si la app se sirve por https (como en Render), marcamos la cookie de
# sesión como "Secure": el navegador entonces solo la envía por https.
# Detectado automáticamente a partir de PUBLIC_BASE_URL, sin necesidad de
# otra variable de entorno.
SESSION_HTTPS_ONLY = PUBLIC_BASE_URL.startswith("https://")

