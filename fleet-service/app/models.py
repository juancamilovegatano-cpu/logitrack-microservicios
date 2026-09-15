import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

TipoVehiculo = Enum(
    "tractomula", "camion_rigido", "furgon", "van", "moto",
    name="tipo_vehiculo", create_type=True,
)
EstadoVehiculo = Enum(
    "disponible", "en_ruta", "mantenimiento", "fuera_servicio",
    name="estado_vehiculo", create_type=True,
)


class Vehiculo(Base):
    __tablename__ = "vehiculos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    placa: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    tipo: Mapped[str] = mapped_column(TipoVehiculo, nullable=False)
    capacidad_kg: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    capacidad_m3: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False)
    anio: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    vencimiento_seguro: Mapped[date] = mapped_column(Date, nullable=False)
    estado: Mapped[str] = mapped_column(EstadoVehiculo, nullable=False, default="disponible")
    refrigerado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    certificado_hazmat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # NO está en el ER del documento; se agrega porque el endpoint
    # GET /vehiculos/disponibles?zona= no se puede resolver sin ella.
    zona_operacion: Mapped[str] = mapped_column(String(60), nullable=False, default="montería")
    km_actual: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    asignaciones: Mapped[list["Asignacion"]] = relationship(back_populates="vehiculo")

    __table_args__ = (
        CheckConstraint("capacidad_kg > 0", name="ck_veh_capacidad_kg"),
        CheckConstraint("capacidad_m3 > 0", name="ck_veh_capacidad_m3"),
        Index("idx_veh_estado_tipo", "estado", "tipo", "refrigerado"),
        Index("idx_veh_zona", "zona_operacion"),
    )


class Conductor(Base):
    __tablename__ = "conductores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    numero_licencia: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    certificacion_hazmat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    horas_conducidas_semana: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)

    categorias: Mapped[list["ConductorCategoria"]] = relationship(
        back_populates="conductor", cascade="all, delete-orphan"
    )
    asignaciones: Mapped[list["Asignacion"]] = relationship(back_populates="conductor")

    __table_args__ = (
        CheckConstraint("horas_conducidas_semana >= 0", name="ck_cond_horas"),
    )


class ConductorCategoria(Base):
    __tablename__ = "conductor_categorias"

    conductor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conductores.id", ondelete="CASCADE"), primary_key=True
    )
    categoria: Mapped[str] = mapped_column(String(4), primary_key=True)

    conductor: Mapped["Conductor"] = relationship(back_populates="categorias")


class Asignacion(Base):
    __tablename__ = "asignaciones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehiculo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("vehiculos.id"), nullable=False)
    conductor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("conductores.id"), nullable=False)
    desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    vehiculo: Mapped["Vehiculo"] = relationship(back_populates="asignaciones")
    conductor: Mapped["Conductor"] = relationship(back_populates="asignaciones")

    __table_args__ = (
        CheckConstraint("hasta IS NULL OR hasta > desde", name="ck_asig_ventana"),
        Index("idx_asig_vehiculo", "vehiculo_id", "desde"),
        Index("idx_asig_conductor", "conductor_id", "desde"),
    )


class OutboxEvento(Base):
    """Patrón Outbox: se escribe en la MISMA transacción que el cambio de negocio."""

    __tablename__ = "outbox_eventos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agregado_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    publicado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_outbox_pendientes", "publicado_en", "id"),)


class EventoProcesado(Base):
    """Idempotencia del consumidor: un event_id ya visto se descarta."""

    __tablename__ = "eventos_procesados"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    procesado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
