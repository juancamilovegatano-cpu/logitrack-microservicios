"""Consumidor de Maintenance: evalúa telemetry.aggregated contra las reglas.

Aquí se combinan los dos estilos de comunicación:
    ASÍNCRONO  el evento telemetry.aggregated llega por RabbitMQ.
    SÍNCRONO   antes de evaluar, se le pregunta a Fleet por REST qué vehículo es
               ese UUID (tipo, placa, kilometraje). Sin el tipo no se pueden
               aplicar las reglas por tipo de vehículo que exige la ficha 3.6, y
               ese dato es propiedad de Fleet: Maintenance no puede inventarlo ni
               leer su base de datos.
"""

import logging
import uuid

from app import crud
from app.clients import fleet
from app.config import settings
from app.database import SessionLocal
from app.events import bus

log = logging.getLogger("consumer")

EXCHANGES = {settings.exchange_tracking: ["telemetry.aggregated"]}

# métrica del modelo <- campo del evento de telemetría
CAMPOS = {
    "temperatura_motor_c": "temperatura_max_c",
    "km_acumulados": "km_acumulados",
    "horas_motor": "horas_motor",
    "nivel_combustible_pct": "nivel_combustible_pct",
}


def manejar(evento: dict):
    tipo = evento.get("tipo")
    event_id = evento.get("event_id")
    datos = evento.get("datos") or {}

    db = SessionLocal()
    try:
        if crud.ya_procesado(db, event_id):
            log.info("evento %s ya procesado, se descarta", event_id)
            return

        vehiculo_id = datos.get("vehiculo_id")
        # Valores que trae el propio evento: son el plan B si Fleet no responde.
        tipo_vehiculo = datos.get("tipo_vehiculo")
        km_actual = datos.get("km_acumulados")
        placa = None
        origen_datos = "evento"
        abiertas = []

        if vehiculo_id:
            vehiculo_id = uuid.UUID(vehiculo_id)

            # --- LLAMADA REST SÍNCRONA A FLEET ---
            respuesta = fleet.obtener_vehiculo(vehiculo_id)

            if respuesta.estado == "no_encontrado":
                # Fleet contestó y dijo que ese vehículo no existe. Abrir una
                # alerta para un UUID fantasma solo ensucia el calendario del
                # taller, así que se descarta el evento aquí.
                detalle = f"Fleet no reconoce el vehiculo {vehiculo_id}: no se abren alertas"
                crud.marcar_procesado(db, event_id, tipo, detalle)
                db.commit()
                log.warning("procesado %s (%s): %s", tipo, event_id, detalle)
                return

            if respuesta.ok:
                v = respuesta.vehiculo
                tipo_vehiculo = v.get("tipo") or tipo_vehiculo
                placa = v.get("placa")
                if v.get("km_actual") is not None:
                    km_actual = v["km_actual"]
                origen_datos = "fleet"
            else:
                # PLAN B: Fleet no respondió o el circuito está abierto. No se
                # bloquea el procesamiento: se evalúan las reglas con lo que
                # trae el evento. Una alerta sin placa es infinitamente mejor
                # que un motor fundido por no haberla abierto.
                log.warning(
                    "Fleet no disponible (%s); se evalua con los datos del evento",
                    respuesta.detalle,
                )
                origen_datos = "evento (degradado)"

            for metrica, campo in CAMPOS.items():
                valor = datos.get(campo)
                if valor is None:
                    continue
                for regla in crud.reglas_aplicables(db, metrica, tipo_vehiculo):
                    if not crud.dispara(regla, float(valor)):
                        continue
                    if crud.alerta_abierta(db, vehiculo_id, regla.id):
                        log.info("regla %s ya tiene alerta abierta para %s", regla.nombre, vehiculo_id)
                        continue
                    programa = crud.abrir_alerta(
                        db, vehiculo_id, regla, float(valor), km_actual, placa
                    )
                    abiertas.append(f"{regla.nombre}->{programa.id}")

        detalle = ", ".join(abiertas) if abiertas else "sin umbrales superados"
        detalle = f"{detalle} [datos de: {origen_datos}]"
        crud.marcar_procesado(db, event_id, tipo, detalle)
        db.commit()
        log.info("procesado %s (%s): %s", tipo, event_id, detalle)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def loop():
    bus.consumir(EXCHANGES, manejar)
