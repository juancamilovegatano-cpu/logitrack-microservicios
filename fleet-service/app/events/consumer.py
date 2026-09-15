"""Consumidor de Fleet: reacciona a maintenance.alert y shipment.incident."""

import logging
import uuid

from app import crud
from app.config import settings
from app.database import SessionLocal
from app.events import bus

log = logging.getLogger("consumer")

EXCHANGES = {
    settings.exchange_maintenance: ["maintenance.alert", "maintenance.completed"],
    settings.exchange_shipment: ["shipment.incident"],
}


def _vehiculo_id(datos: dict) -> uuid.UUID | None:
    valor = datos.get("vehiculo_id")
    return uuid.UUID(valor) if valor else None


def manejar(evento: dict):
    tipo = evento.get("tipo")
    event_id = evento.get("event_id")
    datos = evento.get("datos") or {}

    db = SessionLocal()
    try:
        if crud.ya_procesado(db, event_id):
            log.info("evento %s ya procesado, se descarta", event_id)
            return

        vehiculo_id = _vehiculo_id(datos)
        detalle = "sin efecto"

        if vehiculo_id:
            vehiculo = crud.obtener_vehiculo(db, vehiculo_id)
            if vehiculo is None:
                detalle = f"vehículo {vehiculo_id} desconocido"
            elif tipo == "maintenance.alert":
                motivo = f"alerta de mantenimiento: {datos.get('metrica', 'n/d')}"
                cambio = crud.cambiar_estado(db, vehiculo, "mantenimiento", motivo)
                detalle = f"{vehiculo.placa} -> mantenimiento" if cambio else "estado ya era mantenimiento"
            elif tipo == "maintenance.completed":
                motivo = f"intervención cerrada en {datos.get('taller', 'taller')}"
                cambio = crud.cambiar_estado(db, vehiculo, "disponible", motivo)
                detalle = f"{vehiculo.placa} -> disponible" if cambio else "estado ya era disponible"
            elif tipo == "shipment.incident":
                motivo = f"incidencia en envío {datos.get('envio_id', 'n/d')}"
                cambio = crud.cambiar_estado(db, vehiculo, "fuera_servicio", motivo)
                detalle = f"{vehiculo.placa} -> fuera_servicio" if cambio else "estado ya era fuera_servicio"

        # el registro de idempotencia y el cambio de estado van juntos
        crud.marcar_procesado(db, event_id, tipo, detalle)
        db.commit()
        log.info("procesado %s (%s): %s", tipo, event_id, detalle)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def loop():
    bus.consumir(EXCHANGES, manejar)
