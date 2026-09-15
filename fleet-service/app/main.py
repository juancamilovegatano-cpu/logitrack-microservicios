import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.database import Base, engine
from app.events import consumer, outbox
from app.routers import conductores, vehiculos

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","nivel":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
log = logging.getLogger(settings.service_name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    if settings.events_enabled:
        threading.Thread(target=outbox.loop, daemon=True, name="outbox").start()
        threading.Thread(target=consumer.loop, daemon=True, name="consumer").start()
        log.info("hilos de bus iniciados")
    yield


app = FastAPI(title="LogiTrack — Fleet Service", version="1.0.0", lifespan=lifespan)
app.include_router(vehiculos.router)
app.include_router(conductores.router)


@app.get("/health", tags=["infra"])
def health():
    return {"status": "ok", "servicio": settings.service_name}


@app.get("/ready", tags=["infra"])
def ready():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001 - readiness debe reportar 503 ante CUALQUIER fallo
        return JSONResponse({"status": "not_ready", "detalle": str(exc)}, status_code=503)
