"""Consumidor de Fleet: reacciona a maintenance.alert y shipment.incident.

Escucha el exchange único del sistema (`logitrack.events`) y lee el sobre
canónico: `event_type` y `payload`.
"""

import logging
import uuid

from app import crud
from app.config import settings
from app.database import SessionLocal
from app.events import bus

log = logging.getLogger("consumer")

EXCHANGES = {
    settings.exchange_eventos: [
        "maintenance.alert",
        "maintenance.completed",
        "shipment.incident",
    ]
}

# Solo estas incidencias inmovilizan un vehículo, y solo si vienen
# confirmadas. Un retraso o una incidencia sin confirmar NO saca un camión
# de servicio: hacerlo paraba flota por un reporte preliminar.
INCIDENCIAS_INMOVILIZAN = {"averia", "accidente"}


def _vehiculo_id(payload: dict) -> uuid.UUID | None:
    """`vehicle_id` del contrato. Un valor que no sea UUID se descarta.

    Sin este guardia, un identificador malformado lanza ValueError, el
    mensaje se reintenta cinco veces y acaba en la DLQ sin que el log diga
    por qué. Mejor descartarlo en la primera pasada y dejarlo escrito.
    """
    valor = payload.get("vehicle_id")
    if not valor:
        return None
    try:
        return uuid.UUID(str(valor))
    except ValueError:
        log.warning("vehicle_id no es un UUID valido, se descarta: %r", valor)
        return None


def _aplicar(db, vehiculo, destino: str, motivo: str, trace_id: str | None = None) -> str:
    """Intenta el cambio de estado y devuelve el detalle para la auditoría.

    `trace_id` es la traza del sobre entrante: el evento derivado la reutiliza
    para que la cadena se siga en los logs (defecto 3.1).

    Una transición prohibida NO es un fallo del mensaje: es el dominio
    diciendo que no. Por ejemplo, un `maintenance.completed` sobre un vehículo
    que mientras tanto quedó `fuera_servicio` por un accidente — el taller
    terminó, pero el camión no vuelve a la calle por eso.

    Si se dejara propagar, el mensaje se reintentaría cinco veces y acabaría
    en la DLQ como si algo estuviera roto. Se registra y se sigue.
    """
    try:
        cambio = crud.cambiar_estado(db, vehiculo, destino, motivo, trace_id=trace_id)
    except crud.TransicionInvalida as exc:
        log.warning("transicion rechazada para %s: %s", vehiculo.placa, exc)
        return f"{vehiculo.placa}: {exc}"
    if cambio:
        return f"{vehiculo.placa} -> {destino}"
    return f"estado ya era {destino}"


def _inmoviliza(payload: dict) -> bool:
    """¿Esta incidencia justifica sacar el vehículo de servicio?"""
    return (
        str(payload.get("tipo", "")).lower() in INCIDENCIAS_INMOVILIZAN
        and bool(payload.get("confirmado"))
    )


def manejar(evento: dict):
    tipo = evento.get("event_type")
    event_id = evento.get("event_id")
    datos = evento.get("payload") or {}
    # Traza del sobre entrante (3.1): los eventos derivados la reutilizan.
    trace_id = evento.get("trace_id")

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
                detalle = _aplicar(db, vehiculo, "mantenimiento", motivo, trace_id=trace_id)
            elif tipo == "maintenance.completed":
                motivo = f"intervención cerrada en {datos.get('taller', 'taller')}"
                detalle = _aplicar(db, vehiculo, "disponible", motivo, trace_id=trace_id)
            elif tipo == "shipment.incident":
                if not _inmoviliza(datos):
                    detalle = (
                        f"incidencia '{datos.get('tipo', 'n/d')}' "
                        f"(confirmado={datos.get('confirmado')}): no inmoviliza"
                    )
                else:
                    motivo = f"incidencia en envío {datos.get('shipment_id', 'n/d')}"
                    detalle = _aplicar(db, vehiculo, "fuera_servicio", motivo, trace_id=trace_id)

        # el registro de idempotencia y el cambio de estado van juntos
        crud.marcar_procesado(db, event_id, tipo, detalle)
        db.commit()
        log.info("procesado %s (%s) trace=%s: %s", tipo, event_id, trace_id, detalle)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def loop():
    bus.consumir(EXCHANGES, manejar)
