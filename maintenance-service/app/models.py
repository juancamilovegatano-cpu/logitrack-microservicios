import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
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
Metrica = Enum(
    "temperatura_motor_c", "km_acumulados", "horas_motor",
    "nivel_combustible_pct", "codigo_obd2",
    name="metrica_mantenimiento", create_type=True,
)
EstadoPrograma = Enum(
    "pendiente", "programado", "en_taller", "completado", "cancelado",
    name="estado_programa", create_type=True,
)
OrigenPrograma = Enum("preventivo", "alerta", name="origen_programa", create_type=True)


class Regla(Base):
    """Umbral que dispara una alerta. tipo_vehiculo NULL = aplica a todos."""

    __tablename__ = "reglas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo_vehiculo: Mapped[str | None] = mapped_column(TipoVehiculo, nullable=True)
    metrica: Mapped[str] = mapped_column(Metrica, nullable=False)
    umbral: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    # 'mayor' dispara si valor > umbral; 'menor' si valor < umbral
    comparador: Mapped[str] = mapped_column(String(5), nullable=False, default="mayor")
    prioridad: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    activa: Mapped[bool] = mapped_column(nullable=False, default=True)

    programas: Mapped[list["ProgramaMantenimiento"]] = relationship(back_populates="regla")

    __table_args__ = (
        CheckConstraint("comparador IN ('mayor','menor')", name="ck_regla_comparador"),
        CheckConstraint("prioridad BETWEEN 1 AND 5", name="ck_regla_prioridad"),
        Index("idx_regla_metrica", "metrica", "activa"),
    )


class ProgramaMantenimiento(Base):
    __tablename__ = "programas_mantenimiento"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    regla_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reglas.id"), nullable=True
    )
    # identificador opaco de otro servicio: NUNCA lleva llave foránea
    vehiculo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    fecha_prevista: Mapped[date] = mapped_column(Date, nullable=False)
    km_previsto: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estado: Mapped[str] = mapped_column(EstadoPrograma, nullable=False, default="pendiente")
    origen: Mapped[str] = mapped_column(OrigenPrograma, nullable=False, default="preventivo")
    prioridad: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    regla: Mapped["Regla"] = relationship(back_populates="programas")
    intervenciones: Mapped[list["Intervencion"]] = relationship(back_populates="programa")

    __table_args__ = (
        Index("idx_prog_vehiculo", "vehiculo_id", "estado"),
        Index("idx_prog_fecha", "fecha_prevista", "estado"),
    )


class Intervencion(Base):
    __tablename__ = "intervenciones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    programa_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("programas_mantenimiento.id"), nullable=False
    )
    realizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    costo: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    taller: Mapped[str] = mapped_column(String(120), nullable=False)
    km_al_servicio: Mapped[int] = mapped_column(Integer, nullable=False)
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)

    programa: Mapped["ProgramaMantenimiento"] = relationship(back_populates="intervenciones")

    __table_args__ = (
        CheckConstraint("costo >= 0", name="ck_interv_costo"),
        CheckConstraint("km_al_servicio >= 0", name="ck_interv_km"),
        Index("idx_interv_programa", "programa_id", "realizado_en"),
    )


class OutboxEvento(Base):
    __tablename__ = "outbox_eventos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agregado_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    publicado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_outbox_pendientes", "publicado_en", "id"),)


class EventoProcesado(Base):
    __tablename__ = "eventos_procesados"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    procesado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
