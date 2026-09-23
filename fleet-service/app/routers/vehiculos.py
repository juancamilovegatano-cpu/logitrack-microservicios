import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db
from app.models import Vehiculo

router = APIRouter(prefix="/api/v1/vehiculos", tags=["vehiculos"])


@router.get("", response_model=schemas.PaginaVehiculos)
def listar(
    estado: schemas.EstadoVehiculoLit | None = None,
    tipo: schemas.TipoVehiculoLit | None = None,
    zona: str | None = None,
    placa: str | None = Query(default=None, max_length=10),
    limite: int = Query(default=50, ge=1, le=200),
    desplazamiento: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Catálogo completo en cualquier estado. Lo consume el panel de operaciones."""
    items, total = crud.listar_vehiculos(db, estado, tipo, zona, placa, limite, desplazamiento)
    return {"total": total, "limite": limite, "desplazamiento": desplazamiento, "items": items}


@router.get("/disponibles", response_model=list[schemas.VehiculoOut])
def listar_disponibles(
    tipo: schemas.TipoVehiculoLit | None = None,
    zona: str | None = None,
    capacidad_min_kg: float | None = Query(default=None, gt=0),
    refrigerado: bool | None = None,
    hazmat: bool | None = None,
    db: Session = Depends(get_db),
):
    """Consulta síncrona que hace Routing antes de asignar una ruta."""
    return crud.vehiculos_disponibles(db, tipo, zona, capacidad_min_kg, refrigerado, hazmat)


@router.get("/{vehiculo_id}", response_model=schemas.VehiculoOut)
def obtener(vehiculo_id: uuid.UUID, db: Session = Depends(get_db)):
    vehiculo = crud.obtener_vehiculo(db, vehiculo_id)
    if vehiculo is None:
        raise HTTPException(404, {"error": "vehiculo_no_encontrado", "mensaje": str(vehiculo_id)})
    return vehiculo


@router.post("", response_model=schemas.VehiculoOut, status_code=status.HTTP_201_CREATED)
def crear(datos: schemas.VehiculoCrear, response: Response, db: Session = Depends(get_db)):
    vehiculo = Vehiculo(**datos.model_dump())
    db.add(vehiculo)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Solo 23505 (unique_violation) es un conflicto de negocio: el resto
        # (clave ajena, CHECK, NOT NULL...) es fallo del servidor y debe
        # llegar como 500, no disfrazado de 409 (defecto 4.3).
        if getattr(exc.orig, "pgcode", None) != "23505":
            raise
        raise HTTPException(
            409, {"error": "placa_duplicada", "mensaje": datos.placa}
        ) from None
    db.refresh(vehiculo)
    response.headers["Location"] = f"/api/v1/vehiculos/{vehiculo.id}"
    return vehiculo


@router.patch("/{vehiculo_id}/estado", response_model=schemas.VehiculoOut)
def cambiar_estado(
    vehiculo_id: uuid.UUID, cambio: schemas.CambioEstado, db: Session = Depends(get_db)
):
    vehiculo = crud.obtener_vehiculo(db, vehiculo_id)
    if vehiculo is None:
        raise HTTPException(404, {"error": "vehiculo_no_encontrado", "mensaje": str(vehiculo_id)})
    try:
        crud.cambiar_estado(db, vehiculo, cambio.estado, cambio.motivo)
    except crud.TransicionInvalida as exc:
        # 422 y no 500: el cliente mandó una petición bien formada pero que
        # el dominio no permite. El mensaje dice qué destinos sí valen.
        db.rollback()
        raise HTTPException(
            422, {"error": "transicion_invalida", "mensaje": str(exc)}
        ) from None
    db.commit()  # estado + fila de outbox en la misma transacción
    db.refresh(vehiculo)
    return vehiculo
