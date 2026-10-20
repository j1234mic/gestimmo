FROM python:3.11-slim

WORKDIR /app
ENV PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=5 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# OCR français/anglais pour la vérification des justificatifs.
# Clients PostgreSQL et MySQL pour les sauvegardes (pg_dump / mysqldump).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-fra postgresql-client default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=300 -r /app/requirements.txt

COPY app/ /app/app/
RUN mkdir -p /app/uploads /app/private_uploads /app/backups

EXPOSE 8000
# Les plateformes managées (Render, Cloud Run, Railway) imposent le port via
# $PORT ; en local et dans docker-compose, on retombe sur 8000.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
