"""consumir(): la republicación confirmada ocurre ANTES del ack (defecto 1.3).

Antes el orden era ack -> publish: entre ambos pasos el mensaje no existía en
ninguna parte, y si el `basic_publish` fallaba (broker caido, justo el
escenario en el que hay reintentos) RabbitMQ ya lo daba por entregado y el
mensaje se perdia para siempre, contradiciendo el at-least-once del README.

Ahora el canal corre en modo confirm (`canal.confirm_delivery()`), se
republica primero y solo tras confirmacion positiva se hace el ack. Si la
publicacion falla, `basic_nack(requeue=True)` y el broker lo reentrega.
"""

import json

import pytest

from app.events import bus


class _FinDePrueba(Exception):
    """Corta el loop infinito de consumir() cuando el test ya respondio."""


class _Metodo:
    delivery_tag = 1


class _Props:
    def __init__(self, headers=None):
        self.headers = headers


class _Conexion:
    def __init__(self, canal):
        self._canal = canal

    def channel(self):
        return self._canal


class _Canal:
    """Canal falso: entrega UN mensaje cuyo `manejar` revienta, y el
    `basic_publish` lanza ConnectionError (broker caido)."""

    def __init__(self):
        self.llamadas = []

    # --- topologia y confirmaciones ------------------------------------
    def confirm_delivery(self):
        self.llamadas.append(("confirm_delivery",))

    def exchange_declare(self, *args, **kwargs): ...

    def queue_declare(self, *args, **kwargs): ...

    def queue_bind(self, *args, **kwargs): ...

    def basic_qos(self, *args, **kwargs): ...

    def consume(self, *args, **kwargs):
        yield _Metodo(), _Props(), json.dumps({"event_type": "prueba.rota"}).encode()
        # nada mas: el `for` termina y consumir() vuelve a reconectar

    # --- acciones bajo prueba ------------------------------------------
    def basic_ack(self, tag):
        self.llamadas.append(("ack", tag))

    def basic_nack(self, tag, requeue=False):
        self.llamadas.append(("nack", tag, requeue))

    def basic_publish(self, *args, **kwargs):
        self.llamadas.append(("publish",))
        raise ConnectionError("broker caido")


def test_basic_publish_fallido_no_ackea_el_mensaje(monkeypatch):
    """Con un basic_publish que lanza, el mensaje NO se ackea (regla del 1.3)."""
    canal = _Canal()
    reconexiones = {"n": 0}

    def _conectar():
        reconexiones["n"] += 1
        if reconexiones["n"] > 1:
            raise _FinDePrueba()  # 2a vuelta: el test ya tiene su respuesta
        return _Conexion(canal)

    def _dormir(_segundos):
        raise _FinDePrueba()

    def _manejar(evento):
        raise RuntimeError("procesamiento roto")  # fuerza la rama de reintentos

    monkeypatch.setattr(bus, "conectar", _conectar)
    monkeypatch.setattr(bus.time, "sleep", _dormir)

    with pytest.raises(_FinDePrueba):
        bus.consumir({"logitrack.events": ["prueba.rota"]}, _manejar)

    # El canal corre en modo confirm: sin eso el fallo del publish es invisible.
    assert ("confirm_delivery",) in canal.llamadas
    # Con el publish lanzando, NO se ackea: el mensaje sigue vivo en la cola...
    assert ("ack", 1) not in canal.llamadas
    # ...y se devuelve al broker para que lo reentregue (requeue=True).
    assert ("nack", 1, True) in canal.llamadas
