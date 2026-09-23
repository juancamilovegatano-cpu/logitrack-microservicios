import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.events import contrato
from app.events.outbox import encolar
from app.models import Asignacion, Conductor, EventoProcesado, Vehiculo

HORAS_MAX_SEMANA = 60  # tope legal usado como regla de disponibilidad


def obtener_vehiculo(db: Session, vehiculo_id: uuid.UUID) -> Vehiculo | None:
    return db.get(Vehiculo, vehiculo_id)


def listar_vehiculos(
    db: Session,
    estado: str | None = None,
    tipo: str | None = None,
    zona: str | None = None,
    placa: str | None = None,
    limite: int = 50,
    desplazamiento: int = 0,
) -> tuple[list[Vehiculo], int]:
    """Listado paginado del catálogo completo, en CUALQUIER estado.

    NO está en la ficha 3.2 del documento: `disponibles` filtra por definición
    `estado == disponible`, así que un panel de operaciones no podría ver — ni
    devolver a servicio — un vehículo que una alerta mandó a 'mantenimiento'.

    Devuelve (página, total) para que el cliente pueda paginar sin adivinar.
    """
    filtros = []
    if estado:
        filtros.append(Vehiculo.estado == estado)
    if tipo:
        filtros.append(Vehiculo.tipo == tipo)
    if zona:
        filtros.append(Vehiculo.zona_operacion == zona)
    if placa:
        filtros.append(Vehiculo.placa.ilike(f"%{placa}%"))

    total = db.scalar(select(func.count()).select_from(Vehiculo).where(*filtros)) or 0
    pagina = db.scalars(
        select(Vehiculo)
        .where(*filtros)
        .order_by(Vehiculo.placa)
        .limit(limite)
        .offset(desplazamiento)
    ).all()
    return list(pagina), total


def listar_conductores(db: Session, nombre: str | None = None) -> list[Conductor]:
    """Catálogo de conductores. selectinload evita el N+1 sobre categorías."""
    q = select(Conductor).options(selectinload(Conductor.categorias))
    if nombre:
        q = q.where(Conductor.nombre.ilike(f"%{nombre}%"))
    return list(db.scalars(q.order_by(Conductor.nombre)).all())


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


# Máquina de estados del vehículo: de cada estado, a cuáles se puede pasar.
#
# La regla que obliga a declararla: un vehículo `fuera_servicio` NO vuelve a
# operar directamente. Tiene que pasar por taller (`mantenimiento`). Sin esta
# tabla, un PATCH podía devolver a la calle un camión accidentado.
TRANSICIONES: dict[str, set[str]] = {
    "disponible": {"en_ruta", "mantenimiento", "fuera_servicio"},
    "en_ruta": {"disponible", "mantenimiento", "fuera_servicio"},
    "mantenimiento": {"disponible", "fuera_servicio"},
    "fuera_servicio": {"mantenimiento"},
}


class TransicionInvalida(ValueError):
    """El estado destino no es alcanzable desde el actual."""

    def __init__(self, actual: str, destino: str) -> None:
        self.actual = actual
        self.destino = destino
        permitidos = ", ".join(sorted(TRANSICIONES.get(actual, set()))) or "ninguno"
        super().__init__(
            f"no se puede pasar de '{actual}' a '{destino}'; desde '{actual}' "
            f"solo se permite: {permitidos}"
        )


def transicion_permitida(actual: str, destino: str) -> bool:
    return destino in TRANSICIONES.get(actual, set())


def cambiar_estado(db: Session, vehiculo: Vehiculo, nuevo_estado: str, motivo: str) -> bool:
    """Cambia el estado y encola vehicle.status_changed en la MISMA transacción.

    Devuelve False si el estado no cambió (no se publica evento redundante).
    Lanza TransicionInvalida si el salto no está permitido.
    El commit lo hace el llamador.
    """
    if vehiculo.estado == nuevo_estado:
        return False
    if not transicion_permitida(vehiculo.estado, nuevo_estado):
        raise TransicionInvalida(vehiculo.estado, nuevo_estado)

    anterior = vehiculo.estado
    vehiculo.estado = nuevo_estado
    # El payload va en el vocabulario del CONTRATO, no en el de la base.
    encolar(
        db,
        tipo="vehicle.status_changed",
        agregado_id=vehiculo.id,
        datos=contrato.payload_status_changed(vehiculo, anterior, nuevo_estado, motivo),
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
