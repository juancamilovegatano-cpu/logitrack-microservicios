import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db
from app.models import Conductor, ConductorCategoria

router = APIRouter(prefix="/api/v1/conductores", tags=["conductores"])


def _salida(conductor: Conductor) -> dict:
    return {
        "id": conductor.id,
        "nombre": conductor.nombre,
        "numero_licencia": conductor.numero_licencia,
        "certificacion_hazmat": conductor.certificacion_hazmat,
        "horas_conducidas_semana": conductor.horas_conducidas_semana,
        "categorias": sorted(c.categoria for c in conductor.categorias),
    }


@router.get("", response_model=list[schemas.ConductorOut])
def listar(
    nombre: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
):
    """Catálogo de conductores. Tampoco está en la ficha 3.2: sin él el panel
    no puede consultar la disponibilidad de nadie sin conocer su UUID de memoria."""
    return [_salida(c) for c in crud.listar_conductores(db, nombre)]


@router.post("", response_model=schemas.ConductorOut, status_code=status.HTTP_201_CREATED)
def crear(datos: schemas.ConductorCrear, db: Session = Depends(get_db)):
    conductor = Conductor(
        nombre=datos.nombre,
        numero_licencia=datos.numero_licencia,
        certificacion_hazmat=datos.certificacion_hazmat,
    )
    conductor.categorias = [ConductorCategoria(categoria=c.upper()) for c in datos.categorias]
    db.add(conductor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409, {"error": "licencia_duplicada", "mensaje": datos.numero_licencia}
        ) from None
    db.refresh(conductor)
    return _salida(conductor)


@router.get("/{conductor_id}/disponibilidad", response_model=schemas.DisponibilidadConductor)
def disponibilidad(conductor_id: uuid.UUID, db: Session = Depends(get_db)):
    conductor = db.get(Conductor, conductor_id)
    if conductor is None:
        raise HTTPException(404, {"error": "conductor_no_encontrado", "mensaje": str(conductor_id)})
    return crud.disponibilidad_conductor(db, conductor)
