"""Publicador del outbox de Maintenance (idéntico en estructura al de Fleet)."""

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.events import bus
from app.models import OutboxEvento

log = logging.getLogger("outbox")


def encolar(db, tipo: str, agregado_id, datos: dict) -> OutboxEvento:
    fila = OutboxEvento(agregado_id=agregado_id, tipo=tipo, payload=datos)
    db.add(fila)
    return fila


def _publicar_lote(canal) -> int:
    db = SessionLocal()
    try:
        pendientes = db.scalars(
            select(OutboxEvento)
            .where(OutboxEvento.publicado_en.is_(None))
            .order_by(OutboxEvento.id)
            .limit(settings.outbox_batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        for fila in pendientes:
            evento = bus.sobre(tipo=fila.tipo, agregado_id=fila.agregado_id, datos=fila.payload)
            bus.publicar(canal, settings.exchange_propio, evento)
            fila.publicado_en = datetime.now(UTC)
        db.commit()
        return len(pendientes)
    finally:
        db.close()


def loop():
    while True:
        try:
            conexion = bus.conectar()
            canal = conexion.channel()
            bus.declarar_topologia(canal)
            canal.confirm_delivery()
            log.info("publicador de outbox activo")
            while True:
                n = _publicar_lote(canal)
                if n:
                    log.info("publicados %s eventos", n)
                time.sleep(settings.outbox_poll_seconds)
        except Exception:
            log.exception("publicador caído; reintentando en 5s")
            time.sleep(5)
