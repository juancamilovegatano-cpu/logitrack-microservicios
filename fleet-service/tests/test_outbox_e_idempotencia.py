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


def _evento(
    event_type: str, vehiculo_id: str, event_id: str | None = None, **extra
) -> dict:
    """Sobre canónico del sistema: event_type / payload.

    El primer parámetro se llama `event_type` y no `tipo` a propósito: `tipo` es
    una clave del payload (el tipo de incidencia de `shipment.incident`), y si el
    parámetro se llamara igual, `_evento("shipment.incident", id, tipo="averia")`
    chocaría contra el posicional en vez de entrar por **extra.
    """
    payload = {
        "vehicle_id": vehiculo_id,
        "metrica": "temperatura_motor_c",
        "taller": "Central",
    }
    payload.update(extra)
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": "2026-01-01T00:00:00+00:00",
        "producer": "maintenance-service",
        "trace_id": uuid.uuid4().hex,
        "payload": payload,
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
    # El payload sale traducido al vocabulario del contrato (contrato.py):
    # la base guarda 'disponible'/'en_ruta', el evento publica
    # 'activo'/'en_transito', que es lo que Routing valida.
    assert filas[0].payload["estado_anterior"] == "activo"
    assert filas[0].payload["estado_nuevo"] == "en_transito"
    assert filas[0].payload["asignable"] is False


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
    consumer.manejar(
        _evento("shipment.incident", vehiculo["id"], tipo="averia", confirmado=True)
    )
    assert db.get(Vehiculo, uuid.UUID(vehiculo["id"])).estado == "fuera_servicio"


def test_incidente_sin_confirmar_no_inmoviliza(db, vehiculo):
    """Una avería reportada pero sin confirmar no para el camión.

    Es el caso que motivó la regla: un reporte preliminar del conductor no
    puede sacar de operación un vehículo que quizá siga perfectamente.
    """
    consumer.manejar(
        _evento("shipment.incident", vehiculo["id"], tipo="averia", confirmado=False)
    )
    assert db.get(Vehiculo, uuid.UUID(vehiculo["id"])).estado == "disponible"
    assert db.scalars(select(OutboxEvento)).all() == []


def test_incidencia_leve_confirmada_tampoco_inmoviliza(db, vehiculo):
    """Un retraso confirmado es una incidencia real, pero no inmoviliza."""
    consumer.manejar(
        _evento("shipment.incident", vehiculo["id"], tipo="retraso", confirmado=True)
    )
    assert db.get(Vehiculo, uuid.UUID(vehiculo["id"])).estado == "disponible"


def test_transicion_invalida_no_revienta_el_consumidor(db, vehiculo):
    """fuera_servicio -> disponible está prohibido: se registra y se sigue.

    El taller cerró la intervención, pero mientras tanto el vehículo quedó
    fuera de servicio por un accidente. El dominio dice que no vuelve a la
    calle por un maintenance.completed, y ese 'no' no puede acabar en la DLQ.
    """
    consumer.manejar(
        _evento("shipment.incident", vehiculo["id"], tipo="accidente", confirmado=True)
    )
    consumer.manejar(_evento("maintenance.completed", vehiculo["id"]))

    assert db.get(Vehiculo, uuid.UUID(vehiculo["id"])).estado == "fuera_servicio"
    # los dos eventos quedan marcados como procesados: ninguno se reintenta
    assert len(db.scalars(select(EventoProcesado)).all()) == 2


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
