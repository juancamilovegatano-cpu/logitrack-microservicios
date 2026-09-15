import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events.outbox import encolar
from app.models import EventoProcesado, Intervencion, ProgramaMantenimiento, Regla

# Cuántos días adelante se programa la visita al taller según prioridad (1 = más urgente)
DIAS_POR_PRIORIDAD = {1: 0, 2: 1, 3: 3, 4: 7, 5: 15}
# Ciclo preventivo tras una intervención
KM_CICLO_PREVENTIVO = 15_000
DIAS_CICLO_PREVENTIVO = 180


def reglas_aplicables(db: Session, metrica: str, tipo_vehiculo: str | None) -> list[Regla]:
    q = select(Regla).where(Regla.metrica == metrica, Regla.activa.is_(True))
    if tipo_vehiculo:
        q = q.where((Regla.tipo_vehiculo == tipo_vehiculo) | (Regla.tipo_vehiculo.is_(None)))
    else:
        q = q.where(Regla.tipo_vehiculo.is_(None))
    return list(db.scalars(q.order_by(Regla.prioridad)).all())


def dispara(regla: Regla, valor: float) -> bool:
    umbral = float(regla.umbral)
    return valor > umbral if regla.comparador == "mayor" else valor < umbral


def alerta_abierta(db: Session, vehiculo_id: uuid.UUID, regla_id: uuid.UUID) -> ProgramaMantenimiento | None:
    """Evita abrir una alerta nueva por la misma regla si ya hay una sin cerrar."""
    return db.scalars(
        select(ProgramaMantenimiento)
        .where(
            ProgramaMantenimiento.vehiculo_id == vehiculo_id,
            ProgramaMantenimiento.regla_id == regla_id,
            ProgramaMantenimiento.estado.in_(["pendiente", "programado", "en_taller"]),
        )
        .limit(1)
    ).first()


def abrir_alerta(
    db: Session,
    vehiculo_id: uuid.UUID,
    regla: Regla,
    valor: float,
    km_actual: int | None = None,
    placa: str | None = None,
) -> ProgramaMantenimiento:
    """Crea el programa y encola maintenance.alert en la misma transacción.

    `placa` llega de la consulta REST síncrona a Fleet. Es None cuando Fleet no
    respondió (plan B del circuit breaker): la alerta se abre igual.
    """
    programa = ProgramaMantenimiento(
        regla_id=regla.id,
        vehiculo_id=vehiculo_id,
        fecha_prevista=date.today() + timedelta(days=DIAS_POR_PRIORIDAD.get(regla.prioridad, 3)),
        km_previsto=km_actual,
        estado="pendiente",
        origen="alerta",
        prioridad=regla.prioridad,
        motivo=(
            f"{regla.nombre}: {regla.metrica}={valor} "
            f"({regla.comparador} que {regla.umbral})"
            + (f" — vehículo {placa}" if placa else "")
        ),
    )
    db.add(programa)
    db.flush()  # para tener programa.id dentro de la misma transacción

    encolar(
        db,
        tipo="maintenance.alert",
        agregado_id=programa.id,
        datos={
            "programa_id": str(programa.id),
            "vehiculo_id": str(vehiculo_id),
            "placa": placa,  # enriquecido por la consulta síncrona a Fleet
            "regla": regla.nombre,
            "metrica": regla.metrica,
            "valor": valor,
            "umbral": float(regla.umbral),
            "prioridad": regla.prioridad,
            "fecha_prevista": programa.fecha_prevista.isoformat(),
        },
    )
    return programa


def programar(db: Session, programa: ProgramaMantenimiento) -> None:
    programa.estado = "programado"
    encolar(
        db,
        tipo="maintenance.scheduled",
        agregado_id=programa.id,
        datos={
            "programa_id": str(programa.id),
            "vehiculo_id": str(programa.vehiculo_id),
            "fecha_prevista": programa.fecha_prevista.isoformat(),
            "km_previsto": programa.km_previsto,
            "prioridad": programa.prioridad,
            "origen": programa.origen,
        },
    )


def registrar_intervencion(db: Session, datos) -> Intervencion:
    """Cierra el programa, publica maintenance.completed y abre el siguiente ciclo preventivo."""
    programa = db.get(ProgramaMantenimiento, datos.programa_id)
    if programa is None:
        raise LookupError("programa_no_encontrado")
    if programa.estado == "completado":
        raise ValueError("programa_ya_completado")

    intervencion = Intervencion(
        programa_id=programa.id,
        realizado_en=datos.realizado_en,
        costo=Decimal(datos.costo),
        taller=datos.taller,
        km_al_servicio=datos.km_al_servicio,
        notas=datos.notas,
    )
    db.add(intervencion)
    programa.estado = "completado"

    # maintenance.completed NO está en el catálogo del documento; se añade porque
    # sin él ningún servicio puede devolver el vehículo a 'disponible'.
    encolar(
        db,
        tipo="maintenance.completed",
        agregado_id=programa.id,
        datos={
            "programa_id": str(programa.id),
            "vehiculo_id": str(programa.vehiculo_id),
            "realizado_en": datos.realizado_en.isoformat(),
            "costo": float(datos.costo),
            "taller": datos.taller,
            "km_al_servicio": datos.km_al_servicio,
        },
    )

    siguiente = ProgramaMantenimiento(
        regla_id=None,
        vehiculo_id=programa.vehiculo_id,
        fecha_prevista=datos.realizado_en.date() + timedelta(days=DIAS_CICLO_PREVENTIVO),
        km_previsto=datos.km_al_servicio + KM_CICLO_PREVENTIVO,
        estado="programado",
        origen="preventivo",
        prioridad=4,
        motivo="ciclo preventivo tras intervención",
    )
    db.add(siguiente)
    db.flush()
    programar(db, siguiente)

    return intervencion


def programa_de_vehiculo(db: Session, vehiculo_id: uuid.UUID) -> list[ProgramaMantenimiento]:
    return list(
        db.scalars(
            select(ProgramaMantenimiento)
            .where(ProgramaMantenimiento.vehiculo_id == vehiculo_id)
            .order_by(ProgramaMantenimiento.fecha_prevista.desc())
        ).all()
    )


def proximos(db: Session, dias: int) -> list[ProgramaMantenimiento]:
    limite = date.today() + timedelta(days=dias)
    return list(
        db.scalars(
            select(ProgramaMantenimiento)
            .where(
                ProgramaMantenimiento.fecha_prevista <= limite,
                ProgramaMantenimiento.estado.in_(["pendiente", "programado"]),
            )
            .order_by(ProgramaMantenimiento.fecha_prevista, ProgramaMantenimiento.prioridad)
        ).all()
    )


def alertas(db: Session, estado: str) -> list[ProgramaMantenimiento]:
    estados = (
        ["pendiente", "programado", "en_taller"] if estado == "abierta" else ["completado", "cancelado"]
    )
    return list(
        db.scalars(
            select(ProgramaMantenimiento)
            .where(
                ProgramaMantenimiento.origen == "alerta",
                ProgramaMantenimiento.estado.in_(estados),
            )
            .order_by(ProgramaMantenimiento.prioridad, ProgramaMantenimiento.creado_en.desc())
        ).all()
    )


def ya_procesado(db: Session, event_id: str) -> bool:
    return db.get(EventoProcesado, uuid.UUID(event_id)) is not None


def marcar_procesado(db: Session, event_id: str, tipo: str, detalle: str = ""):
    db.add(EventoProcesado(event_id=uuid.UUID(event_id), tipo=tipo, detalle=detalle[:500]))
