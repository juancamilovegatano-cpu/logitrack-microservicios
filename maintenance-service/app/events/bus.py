"""Cliente RabbitMQ: topología, publicación y consumo con DLQ.

Topología (idéntica en los cinco microservicios):
  exchange topic  logitrack.events      -> único; la routing key es el event_type
  exchange topic  logitrack.dlx         -> dead letter exchange comun
  cola  <servicio>.inbox                -> una por servicio, durable, con DLQ
  cola  <servicio>.inbox.dlq            -> mensajes que fallaron 5 veces
"""

import json
import logging
import time
import uuid
from datetime import UTC, datetime

import pika

from app.config import settings

log = logging.getLogger("bus")

MAX_REINTENTOS = 5


def conectar() -> pika.BlockingConnection:
    params = pika.URLParameters(settings.rabbitmq_url)
    params.heartbeat = 30
    params.blocked_connection_timeout = 15
    return pika.BlockingConnection(params)


def declarar_topologia(canal, exchanges_a_consumir: dict[str, list[str]] | None = None):
    """exchanges_a_consumir: {exchange: [routing_keys]} que se bindean a la cola del servicio."""
    canal.exchange_declare(settings.dlx_name, exchange_type="topic", durable=True)
    cola_dlq = f"{settings.queue_name}.dlq"
    canal.queue_declare(cola_dlq, durable=True)
    canal.queue_bind(cola_dlq, settings.dlx_name, routing_key=f"{settings.queue_name}.#")

    # Exchange único del sistema: se declara siempre, se publique o se consuma.
    canal.exchange_declare(settings.exchange_eventos, exchange_type="topic", durable=True)

    if exchanges_a_consumir:
        canal.queue_declare(
            settings.queue_name,
            durable=True,
            arguments={
                "x-dead-letter-exchange": settings.dlx_name,
                "x-dead-letter-routing-key": f"{settings.queue_name}.fallido",
            },
        )
        for exchange, routing_keys in exchanges_a_consumir.items():
            canal.exchange_declare(exchange, exchange_type="topic", durable=True)
            for rk in routing_keys:
                canal.queue_bind(settings.queue_name, exchange, routing_key=rk)


def sobre(tipo: str, agregado_id, datos: dict, event_id: str | None = None) -> dict:
    """Sobre canónico del sistema. Lo comparten los cinco microservicios.

        {event_id, event_type, occurred_at, producer, trace_id, payload}

    `event_id` es la llave de idempotencia del consumidor: se conserva si el
    llamador lo trae, para que un reintento del outbox no genere uno nuevo.

    `agregado_id` se mantiene en la firma porque el outbox lo pasa, pero NO
    viaja en el sobre: el identificador del agregado ya va dentro del payload
    de cada evento, y duplicarlo abría la puerta a que los dos valores se
    contradijeran.

    `trace_id` se genera aquí cuando no existe. Sin él, seguir una operación
    que atraviesa cuatro servicios en los logs es imposible.
    """
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": tipo,
        "occurred_at": datetime.now(UTC).isoformat(),
        "producer": settings.service_name,
        "trace_id": uuid.uuid4().hex,
        "payload": datos,
    }


def publicar(canal, exchange: str, evento: dict):
    canal.basic_publish(
        exchange=exchange,
        routing_key=evento["event_type"],
        body=json.dumps(evento, default=str).encode(),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,  # persistente
            message_id=evento["event_id"],
            type=evento["event_type"],
            headers={"trace_id": evento.get("trace_id") or "-"},
        ),
    )


def consumir(exchanges: dict[str, list[str]], manejar, prefetch: int = 20):
    """Loop bloqueante con reconexión. `manejar(evento) -> None`.

    Si manejar lanza excepción, el mensaje se reencola hasta MAX_REINTENTOS y
    después va a la DLQ (nack sin requeue).
    """
    while True:
        try:
            conexion = conectar()
            canal = conexion.channel()
            # Modo confirm: en este canal basic_publish solo da por bueno lo
            # que el broker confirmo. Sin esto, un publish con el broker
            # caido "parece" exitoso y el ack posterior seria a ciegas.
            canal.confirm_delivery()
            declarar_topologia(canal, exchanges)
            canal.basic_qos(prefetch_count=prefetch)
            log.info("consumidor escuchando en %s", settings.queue_name)

            for metodo, props, body in canal.consume(settings.queue_name, inactivity_timeout=5):
                if metodo is None:
                    continue
                try:
                    evento = json.loads(body)
                    manejar(evento)
                    canal.basic_ack(metodo.delivery_tag)
                except Exception:
                    intentos = (props.headers or {}).get("x-intentos", 0) + 1
                    log.exception("fallo procesando mensaje (intento %s)", intentos)
                    if intentos >= MAX_REINTENTOS:
                        canal.basic_nack(metodo.delivery_tag, requeue=False)  # -> DLQ
                    else:
                        props.headers = {**(props.headers or {}), "x-intentos": intentos}
                        # Primero la republicacion CONFIRMADA y despues el ack.
                        # Con el orden anterior, entre el ack y el publish el
                        # mensaje no existia en ninguna parte: si el publish
                        # fallaba (broker caido, justo cuando hay reintentos)
                        # RabbitMQ ya lo daba por entregado y se perdia.
                        try:
                            confirmado = canal.basic_publish(
                                exchange="",
                                routing_key=settings.queue_name,
                                body=body,
                                properties=props,
                            )
                        except Exception:
                            log.exception(
                                "republicacion no confirmada; se reencola el mensaje original"
                            )
                            canal.basic_nack(metodo.delivery_tag, requeue=True)
                            continue
                        if confirmado is False:  # el broker la rechazo (nack)
                            log.error(
                                "broker rechazo la republicacion; se reencola el mensaje original"
                            )
                            canal.basic_nack(metodo.delivery_tag, requeue=True)
                            continue
                        canal.basic_ack(metodo.delivery_tag)
        except Exception:
            log.exception("conexión al bus perdida; reintentando en 5s")
            time.sleep(5)
