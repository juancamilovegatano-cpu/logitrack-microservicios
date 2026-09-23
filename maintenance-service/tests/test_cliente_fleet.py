"""Cliente REST síncrono hacia Fleet: timeout, reintentos y plan B.

Fleet se sustituye por un transporte falso de httpx. Así se pueden provocar a
voluntad los casos que contra un servicio real son difíciles de reproducir:
timeouts, 500 intermitentes y 404.
"""

import uuid

import httpx
import pytest

from app.clients import fleet
from app.config import settings

VEHICULO = {
    # VehiculoOut real: id, placa, tipo, estado... Sin km_actual: Fleet no
    # almacena kilometraje (defecto 3.2), el doble no puede inventarlo.
    "id": str(uuid.uuid4()),
    "placa": "ABC123",
    "tipo": "tractomula",
    "estado": "disponible",
}


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    """Acorta el backoff: la política ya se verifica en test_circuit_breaker."""
    monkeypatch.setattr(settings, "rest_backoff_base_segundos", 0.01)
    monkeypatch.setattr(settings, "rest_jitter_maximo_segundos", 0.0)


def _instalar(monkeypatch, manejador):
    """Reemplaza el cliente HTTP por uno que responde con `manejador`."""
    transporte = httpx.MockTransport(manejador)
    falso = httpx.Client(
        transport=transporte,
        base_url="http://fleet-service:8000",
        timeout=httpx.Timeout(settings.rest_timeout_segundos),
    )
    monkeypatch.setattr(fleet, "_cliente", falso)


# ------------------------------------------------------------- camino feliz


def test_200_devuelve_el_vehiculo(monkeypatch):
    _instalar(monkeypatch, lambda _: httpx.Response(200, json=VEHICULO))
    respuesta = fleet.obtener_vehiculo(VEHICULO["id"])
    assert respuesta.ok
    assert respuesta.estado == "ok"
    assert respuesta.vehiculo["placa"] == "ABC123"
    assert respuesta.vehiculo["tipo"] == "tractomula"


def test_pide_la_ruta_correcta(monkeypatch):
    vistas = []

    def manejador(peticion):
        vistas.append(peticion.url.path)
        return httpx.Response(200, json=VEHICULO)

    _instalar(monkeypatch, manejador)
    fleet.obtener_vehiculo(VEHICULO["id"])
    assert vistas == [f"/api/v1/vehiculos/{VEHICULO['id']}"]


# ------------------------------------------------------------------- 404


def test_404_es_respuesta_valida_no_fallo(monkeypatch):
    """Fleet contestó, y contestó que no existe. No es indisponibilidad:
    no se reintenta y no cuenta para abrir el circuito."""
    llamadas = []

    def manejador(peticion):
        llamadas.append(peticion)
        return httpx.Response(404, json={"detail": "no existe"})

    _instalar(monkeypatch, manejador)
    respuesta = fleet.obtener_vehiculo(uuid.uuid4())

    assert respuesta.estado == "no_encontrado"
    assert respuesta.ok is False
    assert len(llamadas) == 1  # NO se reintentó
    assert fleet.breaker.instantanea()["fallos_en_ventana"] == 0


# ------------------------------------------------------------- reintentos


def test_reintenta_hasta_el_maximo_y_se_rinde(monkeypatch):
    llamadas = []

    def manejador(peticion):
        llamadas.append(peticion)
        return httpx.Response(503)

    _instalar(monkeypatch, manejador)
    respuesta = fleet.obtener_vehiculo(VEHICULO["id"])

    assert respuesta.estado == "no_disponible"
    assert len(llamadas) == settings.rest_max_intentos  # 3 intentos
    assert fleet.breaker.instantanea()["fallos_en_ventana"] == 1  # 1 fallo, no 3


def test_se_recupera_si_un_reintento_funciona(monkeypatch):
    """Un 500 pasajero no debe degradar el servicio."""
    intentos = {"n": 0}

    def manejador(peticion):
        intentos["n"] += 1
        if intentos["n"] < 3:
            return httpx.Response(500)
        return httpx.Response(200, json=VEHICULO)

    _instalar(monkeypatch, manejador)
    respuesta = fleet.obtener_vehiculo(VEHICULO["id"])

    assert respuesta.ok
    assert intentos["n"] == 3
    assert fleet.breaker.instantanea()["fallos_en_ventana"] == 0


def test_el_timeout_se_trata_como_indisponibilidad(monkeypatch):
    def manejador(peticion):
        raise httpx.TimeoutException("agotado", request=peticion)

    _instalar(monkeypatch, manejador)
    respuesta = fleet.obtener_vehiculo(VEHICULO["id"])
    assert respuesta.estado == "no_disponible"
    assert "timeout" in respuesta.detalle


def test_error_de_red_se_trata_como_indisponibilidad(monkeypatch):
    def manejador(peticion):
        raise httpx.ConnectError("sin ruta al host", request=peticion)

    _instalar(monkeypatch, manejador)
    assert fleet.obtener_vehiculo(VEHICULO["id"]).estado == "no_disponible"


def test_400_no_se_reintenta(monkeypatch):
    """Un error del llamador da lo mismo cuantas veces se repita."""
    llamadas = []

    def manejador(peticion):
        llamadas.append(peticion)
        return httpx.Response(400)

    _instalar(monkeypatch, manejador)
    assert fleet.obtener_vehiculo(VEHICULO["id"]).estado == "no_disponible"
    assert len(llamadas) == 1


# -------------------------------------------------- integración con el breaker


def test_el_circuito_abierto_corta_las_llamadas(monkeypatch):
    llamadas = []

    def manejador(peticion):
        llamadas.append(peticion)
        return httpx.Response(503)

    _instalar(monkeypatch, manejador)

    for _ in range(settings.breaker_umbral_fallos):
        fleet.obtener_vehiculo(VEHICULO["id"])

    assert fleet.breaker.instantanea()["estado"] == "abierto"
    llamadas_antes = len(llamadas)

    respuesta = fleet.obtener_vehiculo(VEHICULO["id"])
    assert respuesta.estado == "no_disponible"
    assert respuesta.detalle == "circuito abierto"
    assert len(llamadas) == llamadas_antes  # ni una petición más salió a la red
