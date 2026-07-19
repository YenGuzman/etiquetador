FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# /data se monta como volumen persistente (base de datos + imágenes subidas)
VOLUME ["/data"]
ENV DATA_DIR=/data

EXPOSE 8000

# Render (y otras plataformas Docker) inyectan la variable PORT en tiempo de
# ejecución y esperan que el servidor escuche ahí. Con CMD en forma "shell"
# (no en forma de lista) sí se expande la variable de entorno. El valor
# 8000 solo se usa como respaldo para pruebas locales con `docker run` sin
# definir PORT.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
