FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Mismo patrón que kevin-logitrack: el proceso no corre como root (4.8).
RUN useradd --create-home --uid 10001 logitrack

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=logitrack:logitrack app ./app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

USER logitrack
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
