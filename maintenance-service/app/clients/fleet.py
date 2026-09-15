"""Cliente REST SÍNCRONO de Maintenance hacia Fleet.

Este es el único punto del sistema donde Maintenance no puede continuar sin la
respuesta del otro servicio, así que aplica la regla de la sección 05 del
documento: "si el que llama no puede continuar sin la respuesta, se usa REST
síncrono; si puede continuar, se publica un evento".

Por qué existe:
    La ficha 3.6 dice que Maintenance compara la telemetría "contra reglas por
    tipo de vehículo". El evento telemetry.aggregated no garantiza traer el tipo,
    y Maintenance no tiene tabla de vehículos (Database per Service). El tipo, la
    placa y el kilometraje son propiedad de Fleet: hay que preguntárselos.

Política de resiliencia implementada (valores del documento, sección 05):
    - Timeout           2 s para llamadas REST internas.
    - Reintentos        máximo 3 intentos, retroceso exponencial 1 s / 2 s / 4 s
                        más jitter aleatorio. Solo sobre GET (idempotente).
    - Circuit breaker   5 fallos en una ventana de 30 s abren el circuito;
                        tras 30 s pasa a semiabierto y deja pasar una sola
                        petición de prueba.
    - Plan B            si el circuito está abierto o Fleet no responde, el
                        llamador sigue con los datos que trae el evento. La
                        alerta se abre igual, solo que sin enriquecer.
"""

import logging
import random
import threading
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings

log = logging.getLogger("cliente.fleet")

CERRADO = "cerrado"
ABIERTO = "abierto"
SEMIABIERTO = "semiabierto"


@dataclass
class RespuestaFleet:
    """Resultado de una consulta a Fleet.

    estado:
        ok             -> Fleet respondió 200 y `vehiculo` trae los datos.
        no_encontrado  -> Fleet respondió 404: el vehículo NO existe. Es una
                          respuesta válida, no un fallo: no abre el circuito.
        no_disponible  -> Fleet no respondió (timeout, error de red, 5xx) o el
                          circuito está abierto. Toca aplicar el plan B.
    """

    estado: str
    vehiculo: dict | None = None
    detalle: str = ""

    @property
    def ok(self) -> bool:
        return self.estado == "ok"


@dataclass
class CircuitBreaker:
    """Los tres estados del documento: cerrado -> abierto -> semiabierto."""

    umbral_fallos: int
    ventana_segundos: float
    espera_abierto_segundos: float

    _estado: str = CERRADO
    _fallos: list[float] = field(default_factory=list)
    _abierto_desde: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def permite_llamada(self) -> bool:
        """True si hay que intentar la llamada; False si se rechaza al instante."""
        with self._lock:
            if self._estado == CERRADO:
                return True
            if self._estado == ABIERTO:
                if time.monotonic() - self._abierto_desde >= self.espera_abierto_segundos:
                    self._estado = SEMIABIERTO
                    log.warning("circuito -> semiabierto: se deja pasar una peticion de prueba")
                    return True
                return False
            # SEMIABIERTO: solo pasa la petición de prueba; el resto se rechaza.
            return False

    def registrar_exito(self) -> None:
        with self._lock:
            if self._estado != CERRADO:
                log.info("circuito -> cerrado: la prueba respondio bien")
            self._estado = CERRADO
            self._fallos.clear()

    def registrar_fallo(self) -> None:
        with self._lock:
            ahora = time.monotonic()
            if self._estado == SEMIABIERTO:
                self._estado = ABIERTO
                self._abierto_desde = ahora
                log.warning("circuito -> abierto: la peticion de prueba volvio a fallar")
                return
            # Solo cuentan los fallos dentro de la ventana deslizante.
            self._fallos = [t for t in self._fallos if ahora - t < self.ventana_segundos]
            self._fallos.append(ahora)
            if len(self._fallos) >= self.umbral_fallos:
                self._estado = ABIERTO
                self._abierto_desde = ahora
                self._fallos.clear()
                log.warning(
                    "circuito -> abierto: %s fallos en %ss",
                    self.umbral_fallos,
                    self.ventana_segundos,
                )

    def instantanea(self) -> dict:
        """Estado actual, para exponerlo por el endpoint de dependencias."""
        with self._lock:
            restante = 0.0
            if self._estado == ABIERTO:
                restante = max(
                    0.0,
                    self.espera_abierto_segundos - (time.monotonic() - self._abierto_desde),
                )
            return {
                "estado": self._estado,
                "fallos_en_ventana": len(self._fallos),
                "umbral_fallos": self.umbral_fallos,
                "ventana_segundos": self.ventana_segundos,
                "segundos_para_semiabierto": round(restante, 1),
            }


breaker = CircuitBreaker(
    umbral_fallos=settings.breaker_umbral_fallos,
    ventana_segundos=settings.breaker_ventana_segundos,
    espera_abierto_segundos=settings.breaker_espera_abierto_segundos,
)

_cliente = httpx.Client(
    base_url=settings.fleet_base_url,
    timeout=httpx.Timeout(settings.rest_timeout_segundos),
    headers={"User-Agent": f"{settings.service_name}/1.0"},
)


def _esperar(intento: int) -> None:
    """Retroceso exponencial 1 s, 2 s, 4 s más jitter aleatorio.

    El jitter evita que todas las réplicas reintenten en el mismo instante y
    vuelvan a tumbar al servicio que apenas se está recuperando.
    """
    base = settings.rest_backoff_base_segundos * (2 ** (intento - 1))
    time.sleep(base + random.uniform(0, settings.rest_jitter_maximo_segundos))


def obtener_vehiculo(vehiculo_id) -> RespuestaFleet:
    """GET /api/v1/vehiculos/{id} contra Fleet. Nunca lanza excepción."""
    ruta = f"/api/v1/vehiculos/{vehiculo_id}"

    if not breaker.permite_llamada():
        log.warning("circuito abierto: no se llama a Fleet, se aplica el plan B")
        return RespuestaFleet("no_disponible", detalle="circuito abierto")

    ultimo_error = "sin detalle"
    for intento in range(1, settings.rest_max_intentos + 1):
        try:
            respuesta = _cliente.get(ruta)

            if respuesta.status_code == 200:
                breaker.registrar_exito()
                return RespuestaFleet("ok", vehiculo=respuesta.json())

            if respuesta.status_code == 404:
                # Respuesta legítima del servicio: contestó, y contestó que no
                # existe. No es un fallo de disponibilidad, no abre el circuito
                # y no se reintenta.
                breaker.registrar_exito()
                return RespuestaFleet("no_encontrado", detalle=f"Fleet no conoce {vehiculo_id}")

            if 400 <= respuesta.status_code < 500:
                # Error del lado del llamador: reintentar da el mismo resultado.
                breaker.registrar_exito()
                return RespuestaFleet("no_disponible", detalle=f"HTTP {respuesta.status_code}")

            ultimo_error = f"HTTP {respuesta.status_code}"

        except httpx.TimeoutException:
            ultimo_error = f"timeout de {settings.rest_timeout_segundos}s"
        except httpx.HTTPError as exc:
            ultimo_error = f"{type(exc).__name__}: {exc}"

        log.warning("intento %s/%s fallo (%s)", intento, settings.rest_max_intentos, ultimo_error)
        if intento < settings.rest_max_intentos:
            _esperar(intento)

    breaker.registrar_fallo()
    return RespuestaFleet("no_disponible", detalle=ultimo_error)


def sondear() -> dict:
    """Ping a /health de Fleet para el endpoint de dependencias."""
    try:
        respuesta = _cliente.get("/health", timeout=httpx.Timeout(settings.rest_timeout_segundos))
        return {"alcanzable": respuesta.status_code == 200, "http": respuesta.status_code}
    except httpx.HTTPError as exc:
        return {"alcanzable": False, "error": f"{type(exc).__name__}"}
