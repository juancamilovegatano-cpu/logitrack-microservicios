"""Publicador del outbox: lee filas no publicadas y las emite al exchange del dominio.

Corre en un hilo aparte. Si RabbitMQ está caído, las filas quedan pendientes
y se publican cuando vuelva: no se pierde ningún evento.
"""

import logging
import time
import uuid as uuid_mod
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.events import bus
from app.models import OutboxEvento

log = logging.getLogger("outbox")


def encolar(db, tipo: str, agregado_id, datos: dict) -> OutboxEvento:
    """Se llama DENTRO de la transacción de negocio. No hace commit."""
    fila = OutboxEvento(
        # El event_id nace aquí, dentro de la transacción: es la identidad
        # estable del evento, no algo que el publicador improvisara al volar.
        event_id=uuid_mod.uuid4(),
        agregado_id=agregado_id,
        tipo=tipo,
        payload=datos,
    )
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
            evento = bus.sobre(
                tipo=fila.tipo,
                agregado_id=fila.agregado_id,
                datos=fila.payload,
                event_id=str(fila.event_id),
            )
            bus.publicar(canal, settings.exchange_eventos, evento)
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
