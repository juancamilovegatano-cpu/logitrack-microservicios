import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.outbox import encolar
from app.models import Asignacion, Conductor, EventoProcesado, Vehiculo

HORAS_MAX_SEMANA = 60  # tope legal usado como regla de disponibilidad


def obtener_vehiculo(db: Session, vehiculo_id: uuid.UUID) -> Vehiculo | None:
    return db.get(Vehiculo, vehiculo_id)


def vehiculos_disponibles(
    db: Session,
    tipo: str | None = None,
    zona: str | None = None,
    capacidad_min_kg: float | None = None,
    refrigerado: bool | None = None,
    hazmat: bool | None = None,
) -> list[Vehiculo]:
    """Consulta que usa Routing antes de asignar una ruta (REST síncrono)."""
    q = select(Vehiculo).where(Vehiculo.estado == "disponible")
    if tipo:
        q = q.where(Vehiculo.tipo == tipo)
    if zona:
        q = q.where(Vehiculo.zona_operacion == zona)
    if capacidad_min_kg is not None:
        q = q.where(Vehiculo.capacidad_kg >= capacidad_min_kg)
    if refrigerado is not None:
        q = q.where(Vehiculo.refrigerado.is_(refrigerado))
    if hazmat is not None:
        q = q.where(Vehiculo.certificado_hazmat.is_(hazmat))
    # el seguro vencido inhabilita el vehículo aunque su estado diga disponible
    q = q.where(Vehiculo.vencimiento_seguro >= datetime.now(UTC).date())
    return list(db.scalars(q.order_by(Vehiculo.capacidad_kg)).all())


def cambiar_estado(db: Session, vehiculo: Vehiculo, nuevo_estado: str, motivo: str) -> bool:
    """Cambia el estado y encola vehicle.status_changed en la MISMA transacción.

    Devuelve False si el estado no cambió (no se publica evento redundante).
    El commit lo hace el llamador.
    """
    if vehiculo.estado == nuevo_estado:
        return False
    anterior = vehiculo.estado
    vehiculo.estado = nuevo_estado
    encolar(
        db,
        tipo="vehicle.status_changed",
        agregado_id=vehiculo.id,
        datos={
            "vehiculo_id": str(vehiculo.id),
            "placa": vehiculo.placa,
            "estado_anterior": anterior,
            "estado_nuevo": nuevo_estado,
            "motivo": motivo,
            "zona_operacion": vehiculo.zona_operacion,
        },
    )
    return True


def ya_procesado(db: Session, event_id: str) -> bool:
    return db.get(EventoProcesado, uuid.UUID(event_id)) is not None


def marcar_procesado(db: Session, event_id: str, tipo: str, detalle: str = ""):
    db.add(EventoProcesado(event_id=uuid.UUID(event_id), tipo=tipo, detalle=detalle[:500]))


def disponibilidad_conductor(db: Session, conductor: Conductor) -> dict:
    ahora = datetime.now(UTC)
    asignacion = db.scalars(
        select(Asignacion)
        .where(
            Asignacion.conductor_id == conductor.id,
            Asignacion.desde <= ahora,
            (Asignacion.hasta.is_(None)) | (Asignacion.hasta > ahora),
        )
        .limit(1)
    ).first()

    horas = float(conductor.horas_conducidas_semana)
    if asignacion is not None:
        disponible, motivo = False, "ya tiene un vehículo asignado en esta ventana"
    elif horas >= HORAS_MAX_SEMANA:
        disponible, motivo = False, f"alcanzó el tope de {HORAS_MAX_SEMANA} h semanales"
    else:
        disponible, motivo = True, "sin asignación activa y con horas disponibles"

    return {
        "conductor_id": conductor.id,
        "disponible": disponible,
        "motivo": motivo,
        "horas_conducidas_semana": conductor.horas_conducidas_semana,
        "horas_restantes": max(HORAS_MAX_SEMANA - horas, 0),
        "vehiculo_asignado": asignacion.vehiculo_id if asignacion else None,
        "consultado_en": ahora,
    }
