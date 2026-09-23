"""Defecto 4.4: POST /intervenciones no tenía ninguna prueba.

Es la transacción con más efectos del sistema (tres): cierra el programa,
publica maintenance.completed y abre el siguiente ciclo preventivo — que a su
vez encola maintenance.scheduled. Si una sola de esas piezas rompe, el
vehículo se queda clavado en 'mantenimiento' para siempre o el evento que lo
devuelve a 'disponible' jamás sale.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app import crud, models


def _programa(db, estado="programado"):
    programa = models.ProgramaMantenimiento(
        vehiculo_id=uuid.uuid4(),
        fecha_prevista=date(2026, 10, 1),
        km_previsto=40000,
        estado=estado,
        origen="preventivo",
        prioridad=3,
        motivo="revisión de rutina",
    )
    db.add(programa)
    db.commit()
    db.refresh(programa)
    return programa


def _intervenir(cliente, programa, realizado_en="2026-09-20T10:00:00Z"):
    return cliente.post(
        "/api/v1/mantenimiento/intervenciones",
        json={
            "programa_id": str(programa.id),
            "realizado_en": realizado_en,
            "costo": 350000,
            "taller": "Taller Central",
            "km_al_servicio": 42000,
            "notas": "cambio de aceite y filtros",
        },
    )


def test_cierra_el_programa_publica_y_abre_el_siguiente_ciclo(cliente, db):
    programa = _programa(db)

    respuesta = _intervenir(cliente, programa)

    assert respuesta.status_code == 201
    assert respuesta.json()["programa_id"] == str(programa.id)

    # Efecto 1: el programa queda completado.
    db.refresh(programa)
    assert programa.estado == "completado"

    # Efecto 2: maintenance.completed queda en el outbox, en la misma
    # transacción (sin él ningún servicio puede devolver el vehículo).
    tipos = [
        fila.tipo
        for fila in db.scalars(
            select(models.OutboxEvento).where(
                models.OutboxEvento.agregado_id == programa.id
            )
        ).all()
    ]
    assert "maintenance.completed" in tipos

    # Efecto 3: se abre el siguiente ciclo preventivo con el próximo
    # fecha/km configurados...
    siguientes = [
        p
        for p in db.scalars(select(models.ProgramaMantenimiento)).all()
        if p.id != programa.id
    ]
    assert len(siguientes) == 1
    nuevo = siguientes[0]
    assert nuevo.estado == "programado"
    assert nuevo.origen == "preventivo"
    assert nuevo.vehiculo_id == programa.vehiculo_id
    assert nuevo.fecha_prevista == date(2026, 9, 20) + timedelta(
        days=crud.DIAS_CICLO_PREVENTIVO
    )
    assert nuevo.km_previsto == 42000 + crud.KM_CICLO_PREVENTIVO

    # ... y su maintenance.scheduled también queda encolado.
    tipos_nuevos = [
        fila.tipo
        for fila in db.scalars(
            select(models.OutboxEvento).where(
                models.OutboxEvento.agregado_id == nuevo.id
            )
        ).all()
    ]
    assert "maintenance.scheduled" in tipos_nuevos


def test_programa_inexistente_devuelve_404(cliente):
    respuesta = cliente.post(
        "/api/v1/mantenimiento/intervenciones",
        json={
            "programa_id": str(uuid.uuid4()),
            "realizado_en": "2026-09-20T10:00:00Z",
            "costo": 100,
            "taller": "Taller Central",
            "km_al_servicio": 1000,
        },
    )
    assert respuesta.status_code == 404
    assert respuesta.json()["detail"]["error"] == "programa_no_encontrado"


def test_programa_ya_completado_devuelve_409(cliente, db):
    programa = _programa(db, estado="completado")

    respuesta = _intervenir(cliente, programa)

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"]["error"] == "programa_ya_completado"


def test_costo_negativo_devuelve_422(cliente, db):
    """La validación de entrada corta antes de tocar la transacción."""
    programa = _programa(db)
    respuesta = cliente.post(
        "/api/v1/mantenimiento/intervenciones",
        json={
            "programa_id": str(programa.id),
            "realizado_en": "2026-09-20T10:00:00Z",
            "costo": -1,
            "taller": "Taller Central",
            "km_al_servicio": 1000,
        },
    )
    assert respuesta.status_code == 422
