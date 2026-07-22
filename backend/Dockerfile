FROM python:3.11-slim

WORKDIR /app

# Augmenter le timeout pip
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=5

# Installer les dépendances
RUN pip install --no-cache-dir --default-timeout=300 fastapi uvicorn[standard] python-dotenv

COPY app/ /app/app/
COPY uploads/ /app/uploads/

RUN mkdir -p /app/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
