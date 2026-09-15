"""Los dos patrones que sostienen la comunicación asíncrona de Fleet.

OUTBOX        el evento se escribe en la MISMA transacción que el cambio de
              negocio. Si una falla, fallan las dos.
IDEMPOTENCIA  RabbitMQ entrega at-least-once: un mensaje repetido no puede
              producir un segundo efecto.
"""

import uuid

from sqlalchemy import select

from app import crud
from app.events import consumer
from app.models import EventoProcesado, OutboxEvento, Vehiculo


def _evento(tipo: str, vehiculo_id: str, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "tipo": tipo,
        "origen": "maintenance-service",
        "agregado_id": vehiculo_id,
        "datos": {"vehiculo_id": vehiculo_id, "metrica": "temperatura_motor_c", "taller": "Central"},
    }


# --------------------------------------------------------------- outbox


def test_cambiar_estado_encola_el_evento_en_la_misma_transaccion(cliente, db, vehiculo):
    cliente.patch(
        f"/api/v1/vehiculos/{vehiculo['id']}/estado",
        json={"estado": "en_ruta", "motivo": "Sale con carga hacia Sincelejo"},
    )
    filas = db.scalars(select(OutboxEvento)).all()
    assert len(filas) == 1
    assert filas[0].tipo == "vehicle.status_changed"
    assert filas[0].publicado_en is None  # todavía sin publicar
    assert filas[0].payload["estado_anterior"] == "disponible"
    assert filas[0].payload["estado_nuevo"] == "en_ruta"


def test_estado_sin_cambio_no_encola_evento_redundante(cliente, db, vehiculo):
    """Pasar a 'disponible' un vehículo que ya está disponible no publica nada."""
    respuesta = cliente.patch(
        f"/api/v1/vehiculos/{vehiculo['id']}/estado",
        json={"estado": "disponible", "motivo": "Confirmación redundante"},
    )
    assert respuesta.status_code == 200
    assert db.scalars(select(OutboxEvento)).all() == []


def test_el_cambio_fallido_no_deja_evento_huerfano(cliente, db):
    """Si el vehículo no existe, no hay cambio de estado NI fila de outbox."""
    respuesta = cliente.patch(
        f"/api/v1/vehiculos/{uuid.uuid4()}/estado",
        json={"estado": "mantenimiento", "motivo": "Vehículo que no existe"},
    )
    assert respuesta.status_code == 404
    assert db.scalars(select(OutboxEvento)).all() == []


# --------------------------------------------------------- idempotencia


def test_maintenance_alert_pone_el_vehiculo_en_mantenimiento(db, vehiculo):
    consumer.manejar(_evento("maintenance.alert", vehiculo["id"]))
    assert db.get(Vehiculo, uuid.UUID(vehiculo["id"])).estado == "mantenimiento"


def test_evento_repetido_se_descarta(db, vehiculo):
    """Mismo event_id dos veces: el segundo no vuelve a actuar."""
    evento = _evento("maintenance.alert", vehiculo["id"])
    consumer.manejar(evento)
    consumer.manejar(evento)  # reentrega

    assert len(db.scalars(select(EventoProcesado)).all()) == 1
    # y no se generó un segundo vehicle.status_changed por el duplicado
    assert len(db.scalars(select(OutboxEvento)).all()) == 1


def test_completed_devuelve_el_vehiculo_a_disponible(db, vehiculo):
    consumer.manejar(_evento("maintenance.alert", vehiculo["id"]))
    consumer.manejar(_evento("maintenance.completed", vehiculo["id"]))
    assert db.get(Vehiculo, uuid.UUID(vehiculo["id"])).estado == "disponible"


def test_incidente_de_envio_saca_el_vehiculo_de_servicio(db, vehiculo):
    consumer.manejar(_evento("shipment.incident", vehiculo["id"]))
    assert db.get(Vehiculo, uuid.UUID(vehiculo["id"])).estado == "fuera_servicio"


def test_evento_de_vehiculo_desconocido_se_marca_sin_reventar(db):
    """Un UUID que Fleet no conoce se registra como procesado y no rompe el consumidor."""
    fantasma = str(uuid.uuid4())
    consumer.manejar(_evento("maintenance.alert", fantasma))
    procesados = db.scalars(select(EventoProcesado)).all()
    assert len(procesados) == 1
    assert "desconocido" in procesados[0].detalle


def test_marcar_procesado_registra_el_event_id(db):
    event_id = str(uuid.uuid4())
    assert crud.ya_procesado(db, event_id) is False
    crud.marcar_procesado(db, event_id, "maintenance.alert", "prueba")
    db.commit()
    assert crud.ya_procesado(db, event_id) is True
