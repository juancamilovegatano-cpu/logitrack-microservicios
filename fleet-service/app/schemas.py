import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TipoVehiculoLit = Literal["tractomula", "camion_rigido", "furgon", "van", "moto"]
EstadoVehiculoLit = Literal["disponible", "en_ruta", "mantenimiento", "fuera_servicio"]


class VehiculoCrear(BaseModel):
    placa: str = Field(min_length=5, max_length=10)
    tipo: TipoVehiculoLit
    capacidad_kg: Decimal = Field(gt=0)
    capacidad_m3: Decimal = Field(gt=0)
    anio: int = Field(ge=1990, le=2100)
    vencimiento_seguro: date
    refrigerado: bool = False
    certificado_hazmat: bool = False
    zona_operacion: str = "montería"


class VehiculoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    placa: str
    tipo: str
    capacidad_kg: Decimal
    capacidad_m3: Decimal
    anio: int
    vencimiento_seguro: date
    estado: str
    refrigerado: bool
    certificado_hazmat: bool
    zona_operacion: str


class PaginaVehiculos(BaseModel):
    """Página del catálogo. `total` es el número de filas que cumplen el filtro,
    no las devueltas: sin él el cliente no puede dibujar la paginación."""

    total: int
    limite: int
    desplazamiento: int
    items: list[VehiculoOut]


class CambioEstado(BaseModel):
    estado: EstadoVehiculoLit
    motivo: str = Field(min_length=3, max_length=200)


class ConductorCrear(BaseModel):
    nombre: str = Field(min_length=3, max_length=120)
    numero_licencia: str = Field(min_length=4, max_length=30)
    certificacion_hazmat: bool = False
    categorias: list[str] = Field(default_factory=list)


class ConductorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    numero_licencia: str
    certificacion_hazmat: bool
    horas_conducidas_semana: Decimal
    categorias: list[str]


class DisponibilidadConductor(BaseModel):
    conductor_id: uuid.UUID
    disponible: bool
    motivo: str
    horas_conducidas_semana: Decimal
    horas_restantes: Decimal
    vehiculo_asignado: uuid.UUID | None
    consultado_en: datetime
