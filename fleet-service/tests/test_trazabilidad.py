"""trace_id propagado de verdad (defecto 3.1).

Antes bus.sobre() generaba un trace_id NUEVO en cada publicación: el
consumidor recibía un evento con su traza y los eventos derivados salían con
otra, así que ninguna traza encadenaba dos servicios — una traza de un solo
salto no es una traza.

Ahora el trace_id entrante viaja hasta el outbox (columna propia) y el sobre
derivado lo reutiliza; solo se genera uno nuevo cuando la operación es el
comienzo de la traza (por ejemplo un HTTP que no trae traza).
"""

import json
import uuid

from sqlalchemy import select

from app.events import bus, consumer, outbox
from app.models import OutboxEvento


class _CanalFalso:
    """Captura los sobres que saldrian al exchange, ya decodificados."""

    def __init__(self):
        self.publicados = []

    def basic_publish(self, *, exchange, routing_key, body, properties):
        self.publicados.append(json.loads(body))


def test_sobre_reutiliza_el_trace_id_cuando_lo_recibe():
    sobre = bus.sobre("vehicle.status_changed", uuid.uuid4(), {}, trace_id="traza-abc")
    assert sobre["trace_id"] == "traza-abc"


def test_encolar_conserva_el_trace_id_hasta_el_sobre_publicado(db):
    outbox.encolar(
        db,
        "vehicle.status_changed",
        uuid.uuid4(),
        {"estado_nuevo": "en_ruta"},
        trace_id="traza-abc",
    )
    db.commit()

    canal = _CanalFalso()
    assert outbox._publicar_lote(canal) == 1
    assert canal.publicados[0]["trace_id"] == "traza-abc"


def test_el_consumidor_propaga_el_trace_id_del_evento_entrante(db, vehiculo):
    """shipment.incident entra con una traza y vehicle.status_changed sale con ella."""
    evento = {
        "event_id": str(uuid.uuid4()),
        "event_type": "shipment.incident",
        "occurred_at": "2026-01-01T00:00:00+00:00",
        "producer": "shipment-service",
        "trace_id": "traza-abc",
        "payload": {
            "vehicle_id": vehiculo["id"],
            "shipment_id": str(uuid.uuid4()),
            "tipo": "averia",
            "confirmado": True,
        },
    }
    consumer.manejar(evento)

    fila = db.scalars(
        select(OutboxEvento).where(OutboxEvento.tipo == "vehicle.status_changed")
    ).one()
    assert fila.trace_id == "traza-abc"

    canal = _CanalFalso()
    outbox._publicar_lote(canal)
    assert canal.publicados[0]["trace_id"] == "traza-abc"
