import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MetricaLit = Literal[
    "temperatura_motor_c", "km_acumulados", "horas_motor", "nivel_combustible_pct", "codigo_obd2"
]
TipoVehiculoLit = Literal["tractomula", "camion_rigido", "furgon", "van", "moto"]
EstadoProgramaLit = Literal["pendiente", "programado", "en_taller", "completado", "cancelado"]


class ReglaCrear(BaseModel):
    nombre: str = Field(min_length=3, max_length=120)
    tipo_vehiculo: TipoVehiculoLit | None = None
    metrica: MetricaLit
    umbral: Decimal
    comparador: Literal["mayor", "menor"] = "mayor"
    prioridad: int = Field(default=3, ge=1, le=5)


class ReglaOut(ReglaCrear):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    activa: bool


class ProgramaCrear(BaseModel):
    vehiculo_id: uuid.UUID
    fecha_prevista: date
    km_previsto: int | None = Field(default=None, ge=0)
    prioridad: int = Field(default=3, ge=1, le=5)
    motivo: str | None = None


class ProgramaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    vehiculo_id: uuid.UUID
    regla_id: uuid.UUID | None
    fecha_prevista: date
    km_previsto: int | None
    estado: str
    origen: str
    prioridad: int
    motivo: str | None
    creado_en: datetime


class IntervencionCrear(BaseModel):
    programa_id: uuid.UUID
    realizado_en: datetime
    costo: Decimal = Field(ge=0)
    taller: str = Field(min_length=2, max_length=120)
    km_al_servicio: int = Field(ge=0)
    notas: str | None = None


class IntervencionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    programa_id: uuid.UUID
    realizado_en: datetime
    costo: Decimal
    taller: str
    km_al_servicio: int
    notas: str | None


# --- Salidas de la comunicación REST síncrona con Fleet ---


class FichaVehiculoOut(BaseModel):
    """Vista combinada: datos del vehículo (de Fleet, por REST síncrono) +
    su historial de mantenimiento (de la BD propia de Maintenance)."""

    vehiculo_id: uuid.UUID
    fuente: Literal["fleet", "no_disponible", "no_encontrado"]
    detalle_consulta: str
    vehiculo: dict | None
    programa: list[ProgramaOut]


class DependenciasOut(BaseModel):
    """Estado de las dependencias síncronas de este servicio."""

    servicio: str
    fleet_base_url: str
    fleet: dict
    circuit_breaker: dict
    politica: dict
