"""Traducción entre el vocabulario interno y el contrato publicado.

La base de datos de Fleet usa su propio vocabulario de estados
(`disponible`, `en_ruta`, `mantenimiento`, `fuera_servicio`) y así lo ve el
panel web. El contrato de eventos del sistema usa otro
(`activo`, `en_transito`, `en_mantenimiento`, `fuera_de_servicio`), que es el
que Routing y Shipment esperan.

Se traduce **al publicar**, no en la base: cambiar el ENUM de PostgreSQL
obligaría a una migración y a tocar el frontend y los 61 tests, a cambio de
nada. Un dominio puede tener su propio lenguaje interno mientras publique el
del sistema; eso es justamente lo que separa el modelo de la API.
"""

# Vocabulario interno (base de datos) -> vocabulario del contrato de eventos.
ESTADOS_A_CONTRATO: dict[str, str] = {
    "disponible": "activo",
    "en_ruta": "en_transito",
    "mantenimiento": "en_mantenimiento",
    "fuera_servicio": "fuera_de_servicio",
}

# Estados del contrato que Routing interpreta como "este vehículo salió de
# operación, recalcula sus rutas".
ESTADOS_FUERA_OPERACION = {"en_mantenimiento", "fuera_de_servicio"}

# Único estado interno en el que un vehículo puede recibir carga.
ESTADO_ASIGNABLE = "disponible"


def a_contrato(estado: str | None) -> str:
    """Interno -> contrato. Un estado desconocido viaja tal cual.

    Passthrough deliberado: si alguien añade un estado y olvida esta tabla,
    prefiero que el evento salga con una etiqueta rara a que salga vacío y el
    consumidor no sepa qué pasó con el vehículo.
    """
    if not estado:
        return ""
    return ESTADOS_A_CONTRATO.get(estado, estado)


def payload_status_changed(vehiculo, anterior: str, nuevo: str, motivo: str) -> dict:
    """Payload de `vehicle.status_changed` tal como lo valida Routing.

    Campos y nombres tomados de VehicleStatusChangedPayload del contrato
    (vehicle_id, plate, estado_anterior, estado_nuevo, asignable, motivo,
    zona, origen).
    """
    return {
        "vehicle_id": str(vehiculo.id),
        "plate": vehiculo.placa,
        "estado_anterior": a_contrato(anterior),
        "estado_nuevo": a_contrato(nuevo),
        # Derivado, no inferido por el consumidor: quien conoce la regla de
        # asignabilidad es Fleet, y así no se replica en cada servicio.
        "asignable": nuevo == ESTADO_ASIGNABLE,
        "motivo": motivo,
        "zona": vehiculo.zona_operacion,
        "origen": "fleet-service",
    }
