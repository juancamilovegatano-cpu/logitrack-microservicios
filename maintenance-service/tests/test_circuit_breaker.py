"""Circuit breaker: los tres estados de la sección 05 del documento.

    cerrado --5 fallos en 30 s--> abierto --tras 30 s--> semiabierto
       ^                                                      |
       +------------- la prueba responde bien ----------------+
                      si vuelve a fallar -> abierto otros 30 s

Son pruebas puras: no tocan la red ni la base de datos. El tiempo se controla
construyendo el breaker con ventanas cortas, para no dormir 30 segundos.
"""

import time

from app.clients.fleet import ABIERTO, CERRADO, SEMIABIERTO, CircuitBreaker


def _breaker(umbral=5, ventana=30.0, espera=30.0) -> CircuitBreaker:
    return CircuitBreaker(
        umbral_fallos=umbral, ventana_segundos=ventana, espera_abierto_segundos=espera
    )


def test_arranca_cerrado_y_deja_pasar():
    cb = _breaker()
    assert cb.instantanea()["estado"] == CERRADO
    assert cb.permite_llamada() is True


def test_los_fallos_por_debajo_del_umbral_no_abren():
    cb = _breaker(umbral=5)
    for _ in range(4):
        cb.registrar_fallo()
    assert cb.instantanea()["estado"] == CERRADO
    assert cb.instantanea()["fallos_en_ventana"] == 4
    assert cb.permite_llamada() is True


def test_el_quinto_fallo_abre_el_circuito():
    cb = _breaker(umbral=5)
    for _ in range(5):
        cb.registrar_fallo()
    assert cb.instantanea()["estado"] == ABIERTO


def test_abierto_rechaza_sin_llamar():
    """El valor del patrón: no se gasta un hilo esperando a un servicio caído."""
    cb = _breaker(umbral=2)
    cb.registrar_fallo()
    cb.registrar_fallo()
    assert cb.permite_llamada() is False


def test_un_exito_reinicia_la_cuenta():
    cb = _breaker(umbral=5)
    for _ in range(4):
        cb.registrar_fallo()
    cb.registrar_exito()
    assert cb.instantanea()["fallos_en_ventana"] == 0
    for _ in range(4):
        cb.registrar_fallo()
    assert cb.instantanea()["estado"] == CERRADO  # 4 + 4 no abren: la cuenta se reinició


def test_los_fallos_viejos_salen_de_la_ventana():
    """Cinco fallos repartidos en horas NO deben abrir el circuito: la regla
    es 5 fallos en 30 segundos, no 5 fallos en total."""
    cb = _breaker(umbral=3, ventana=0.3)
    cb.registrar_fallo()
    cb.registrar_fallo()
    time.sleep(0.35)  # los dos primeros expiran
    cb.registrar_fallo()
    cb.registrar_fallo()
    assert cb.instantanea()["estado"] == CERRADO


def test_pasa_a_semiabierto_tras_la_espera():
    cb = _breaker(umbral=1, espera=0.2)
    cb.registrar_fallo()
    assert cb.permite_llamada() is False  # todavía abierto
    time.sleep(0.25)
    assert cb.permite_llamada() is True  # deja pasar la petición de prueba
    assert cb.instantanea()["estado"] == SEMIABIERTO


def test_semiabierto_deja_pasar_una_sola_peticion():
    cb = _breaker(umbral=1, espera=0.2)
    cb.registrar_fallo()
    time.sleep(0.25)
    assert cb.permite_llamada() is True  # la de prueba
    assert cb.permite_llamada() is False  # el resto se sigue rechazando


def test_si_la_prueba_va_bien_el_circuito_se_cierra():
    cb = _breaker(umbral=1, espera=0.2)
    cb.registrar_fallo()
    time.sleep(0.25)
    cb.permite_llamada()
    cb.registrar_exito()
    assert cb.instantanea()["estado"] == CERRADO
    assert cb.permite_llamada() is True


def test_si_la_prueba_falla_vuelve_a_abrirse():
    cb = _breaker(umbral=5, espera=0.2)
    for _ in range(5):
        cb.registrar_fallo()
    time.sleep(0.25)
    cb.permite_llamada()  # -> semiabierto
    cb.registrar_fallo()  # la prueba falla
    assert cb.instantanea()["estado"] == ABIERTO
    assert cb.permite_llamada() is False


def test_la_instantanea_expone_la_cuenta_regresiva():
    cb = _breaker(umbral=1, espera=30.0)
    cb.registrar_fallo()
    foto = cb.instantanea()
    assert foto["estado"] == ABIERTO
    assert 0 < foto["segundos_para_semiabierto"] <= 30.0
