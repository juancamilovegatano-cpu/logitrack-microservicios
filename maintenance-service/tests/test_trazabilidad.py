"""trace_id propagado de verdad (defecto 3.1).

Antes bus.sobre() generaba un trace_id NUEVO en cada publicación: el
consumidor recibía telemetry.aggregated con su traza y el maintenance.alert
derivado salía con otra, así que la traza se rompía justo al cruzar el
servicio — una traza de un solo salto no es una traza.

Ahora el trace_id entrante viaja hasta el outbox (columna propia) y el sobre
derivado lo reutiliza; solo se genera uno nuevo cuando la operación es el
comienzo de la traza (por ejemplo un HTTP que no trae traza).
"""

import json
import uuid

import pytest
from sqlalchemy import select

from app.clients.fleet import RespuestaFleet
from app.events import bus, consumer, outbox
from app.models import OutboxEvento, Regla

VEHICULO_ID = str(uuid.uuid4())


@pytest.fixture
def regla_general(db):
    regla = Regla(
        nombre="Sobrecalentamiento de motor",
        tipo_vehiculo=None,
        metrica="temperatura_motor_c",
        umbral=105,
        comparador="mayor",
        prioridad=1,
    )
    db.add(regla)
    db.commit()
    return regla


def _telemetria(trace_id="traza-abc", **datos) -> dict:
    """Sobre canónico con la traza que traeria Tracking."""
    cuerpo = {"vehicle_id": VEHICULO_ID, **datos}
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "telemetry.aggregated",
        "occurred_at": "2026-01-01T00:00:00+00:00",
        "producer": "tracking-service",
        "trace_id": trace_id,
        "payload": cuerpo,
    }


class _CanalFalso:
    """Captura los sobres que saldrian al exchange, ya decodificados."""

    def __init__(self):
        self.publicados = []

    def basic_publish(self, *, exchange, routing_key, body, properties):
        self.publicados.append(json.loads(body))


def test_sobre_reutiliza_el_trace_id_cuando_lo_recibe():
    sobre = bus.sobre("maintenance.alert", uuid.uuid4(), {}, trace_id="traza-abc")
    assert sobre["trace_id"] == "traza-abc"


def test_encolar_conserva_el_trace_id_hasta_el_sobre_publicado(db):
    fila = outbox.encolar(
        db, "maintenance.alert", uuid.uuid4(), {"placa": "ABC123"}, trace_id="traza-abc"
    )
    db.commit()

    canal = _CanalFalso()
    assert outbox._publicar_lote(canal) == 1
    assert canal.publicados[0]["trace_id"] == "traza-abc"


def test_el_consumidor_propaga_el_trace_id_del_evento_entrante(
    db, monkeypatch, regla_general
):
    """telemetry.aggregated entra con una traza y maintenance.alert sale con ella.

    El doble de Fleet es la respuesta REAL de GET /vehiculos/{id}: sin
    km_actual, que Fleet no expone (defecto 3.2).
    """
    respuesta = RespuestaFleet(
        "ok", vehiculo={"id": VEHICULO_ID, "placa": "ABC123", "tipo": "camion_rigido"}
    )
    monkeypatch.setattr(consumer.fleet, "obtener_vehiculo", lambda _id: respuesta)

    consumer.manejar(_telemetria(temperatura_motor_max_c=112.4))

    fila = db.scalars(select(OutboxEvento).where(OutboxEvento.tipo == "maintenance.alert")).one()
    assert fila.trace_id == "traza-abc"

    canal = _CanalFalso()
    outbox._publicar_lote(canal)
    assert canal.publicados[0]["trace_id"] == "traza-abc"
