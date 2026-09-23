"""El publicador del outbox: el event_id nace al encolar (defecto 1.4).

Antes el relay no pasaba event_id alguno a bus.sobre(), asi que cada
publicacion de la misma fila salia con un uuid4 distinto. Si el proceso
publicaba y moria antes del commit que marcaba publicado_en, la republicacion
llegaba con otro event_id y los consumidores, que deduplican por event_id,
aplicaban el efecto dos veces: justo lo que el patron outbox existe para
evitar.

Ahora event_id es columna propia de outbox_eventos, se genera en encolar()
dentro de la transaccion de negocio, y conserva ese valor toda su vida.
"""

import json
import uuid

from app.database import SessionLocal
from app.events import outbox
from app.models import OutboxEvento


class _CanalFalso:
    """Captura los sobres que saldrian al exchange, ya decodificados."""

    def __init__(self):
        self.publicados = []

    def basic_publish(self, *, exchange, routing_key, body, properties):
        self.publicados.append(json.loads(body))


def test_el_event_id_se_genera_al_encolar_y_sobrevive_al_commit(db):
    fila = outbox.encolar(
        db, "maintenance.scheduled", uuid.uuid4(), {"programa_id": str(uuid.uuid4())}
    )
    assert fila.event_id is not None  # nace AL ENCOLAR, dentro de la transaccion
    event_id = fila.event_id
    db.commit()

    # Otra sesion, otra conexion: el valor esta en la columna, no en memoria.
    with SessionLocal() as sesion_nueva:
        guardada = sesion_nueva.get(OutboxEvento, fila.id)
        assert guardada.event_id == event_id


def test_republicar_la_misma_fila_produce_dos_sobres_con_el_mismo_event_id(db):
    fila = outbox.encolar(
        db, "maintenance.scheduled", uuid.uuid4(), {"programa_id": str(uuid.uuid4())}
    )
    event_id_al_encolar = str(fila.event_id)
    db.commit()

    canal = _CanalFalso()
    assert outbox._publicar_lote(canal) == 1

    # Simulamos la caida: el broker YA recibio el evento pero el commit que
    # marca publicado_en nunca llego a ejecutarse. La fila sigue pendiente.
    fila = db.get(OutboxEvento, fila.id)
    fila.publicado_en = None
    db.commit()

    assert outbox._publicar_lote(canal) == 1  # la republicacion

    assert len(canal.publicados) == 2
    primero, segundo = canal.publicados
    assert primero["event_id"] == segundo["event_id"]
    assert primero["event_id"] == event_id_al_encolar
