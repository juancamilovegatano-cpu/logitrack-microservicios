import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import crud, schemas
from app.clients import fleet
from app.config import settings
from app.database import get_db
from app.models import Regla

router = APIRouter(prefix="/api/v1/mantenimiento", tags=["mantenimiento"])


@router.post("/reglas", response_model=schemas.ReglaOut, status_code=status.HTTP_201_CREATED)
def crear_regla(datos: schemas.ReglaCrear, db: Session = Depends(get_db)):
    regla = Regla(**datos.model_dump())
    db.add(regla)
    db.commit()
    db.refresh(regla)
    return regla


@router.get("/reglas", response_model=list[schemas.ReglaOut])
def listar_reglas(db: Session = Depends(get_db)):
    return db.query(Regla).order_by(Regla.prioridad).all()


@router.get("/vehiculo/{vehiculo_id}/programa", response_model=list[schemas.ProgramaOut])
def programa_vehiculo(vehiculo_id: uuid.UUID, db: Session = Depends(get_db)):
    return crud.programa_de_vehiculo(db, vehiculo_id)


@router.get("/vehiculo/{vehiculo_id}/ficha", response_model=schemas.FichaVehiculoOut)
def ficha_vehiculo(vehiculo_id: uuid.UUID, db: Session = Depends(get_db)):
    """Vista combinada de un vehículo: COMUNICACIÓN SÍNCRONA en acción.

    Maintenance no tiene tabla de vehículos. Para responder esta ficha hace un
    `GET /api/v1/vehiculos/{id}` contra Fleet y lo une con su propio historial
    de mantenimiento. Si Fleet no responde, devuelve igual la parte que sí es
    suya (`fuente: no_disponible`) en vez de fallar con un 500.
    """
    respuesta = fleet.obtener_vehiculo(vehiculo_id)
    if respuesta.estado == "no_encontrado":
        raise HTTPException(
            404, {"error": "vehiculo_no_encontrado_en_fleet", "mensaje": str(vehiculo_id)}
        )
    return schemas.FichaVehiculoOut(
        vehiculo_id=vehiculo_id,
        fuente="fleet" if respuesta.ok else "no_disponible",
        detalle_consulta=respuesta.detalle or "Fleet respondio 200",
        vehiculo=respuesta.vehiculo,
        programa=crud.programa_de_vehiculo(db, vehiculo_id),
    )


@router.get("/dependencias", response_model=schemas.DependenciasOut, tags=["infra"])
def dependencias():
    """Estado de la dependencia síncrona con Fleet y del circuit breaker.

    Sirve para demostrar en vivo los tres estados del circuito: si apagas Fleet
    (`docker compose stop fleet-service`) y provocas 5 fallos, este endpoint
    muestra `abierto` y la cuenta regresiva hasta `semiabierto`.
    """
    return schemas.DependenciasOut(
        servicio=settings.service_name,
        fleet_base_url=settings.fleet_base_url,
        fleet=fleet.sondear(),
        circuit_breaker=fleet.breaker.instantanea(),
        politica={
            "timeout_segundos": settings.rest_timeout_segundos,
            "max_intentos": settings.rest_max_intentos,
            "backoff_segundos": [
                settings.rest_backoff_base_segundos * (2**i)
                for i in range(settings.rest_max_intentos)
            ],
            "jitter_maximo_segundos": settings.rest_jitter_maximo_segundos,
            "breaker_umbral_fallos": settings.breaker_umbral_fallos,
            "breaker_ventana_segundos": settings.breaker_ventana_segundos,
            "breaker_espera_abierto_segundos": settings.breaker_espera_abierto_segundos,
        },
    )


@router.get("/proximos", response_model=list[schemas.ProgramaOut])
def proximos(
    dias: int = Query(default=settings.dias_proximos_default, ge=1, le=365),
    db: Session = Depends(get_db),
):
    return crud.proximos(db, dias)


@router.get("/alertas", response_model=list[schemas.ProgramaOut])
def alertas(
    estado: str = Query(default="abierta", pattern="^(abierta|cerrada)$"),
    db: Session = Depends(get_db),
):
    return crud.alertas(db, estado)


@router.post(
    "/intervenciones", response_model=schemas.IntervencionOut, status_code=status.HTTP_201_CREATED
)
def registrar_intervencion(datos: schemas.IntervencionCrear, db: Session = Depends(get_db)):
    try:
        intervencion = crud.registrar_intervencion(db, datos)
    except LookupError:
        db.rollback()
        raise HTTPException(404, {"error": "programa_no_encontrado", "mensaje": str(datos.programa_id)})
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, {"error": str(exc), "mensaje": str(datos.programa_id)})
    db.commit()  # intervención + programa + outbox en la misma transacción
    db.refresh(intervencion)
    return intervencion
