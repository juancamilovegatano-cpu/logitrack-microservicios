#!/usr/bin/env python3
"""Prueba end-to-end de los dos servicios.

1. Crea un vehículo en Fleet.
2. Carga una regla de temperatura en Maintenance.
3. Publica telemetry.aggregated simulando al Tracking Ingestion Service.
4. Maintenance abre la alerta y publica maintenance.alert.
5. Fleet consume la alerta y pasa el vehículo a 'mantenimiento'.
6. Se registra la intervención y el vehículo vuelve a 'disponible'.

Uso:  python scripts/demo_e2e.py
"""

import json
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import pika
import requests

FLEET = "http://localhost:8001"
MAINT = "http://localhost:8002"
AMQP = "amqp://logitrack:logitrack@localhost:5672/"
EXCHANGE_EVENTOS = "logitrack.events"


def paso(n, texto):
    print(f"\n\033[94m[{n}]\033[0m {texto}")


def esperar(condicion, descripcion, intentos=25, espera=1.0):
    for _ in range(intentos):
        valor = condicion()
        if valor:
            return valor
        time.sleep(espera)
    print(f"\033[91mFALLO:\033[0m nunca ocurrió -> {descripcion}")
    sys.exit(1)


def main():
    placa = f"XYZ{uuid.uuid4().hex[:3].upper()}"

    paso(1, f"Fleet: creando vehículo {placa}")
    r = requests.post(
        f"{FLEET}/api/v1/vehiculos",
        json={
            "placa": placa,
            "tipo": "camion_rigido",
            "capacidad_kg": 8000,
            "capacidad_m3": 30,
            "anio": 2021,
            "vencimiento_seguro": str(date.today() + timedelta(days=200)),
            "refrigerado": True,
            "zona_operacion": "montería",
            "km_actual": 84000,
        },
        timeout=5,
    )
    r.raise_for_status()
    vehiculo = r.json()
    print("   id:", vehiculo["id"], "| estado:", vehiculo["estado"])

    paso(2, "Maintenance: creando regla de temperatura de motor > 105 °C")
    r = requests.post(
        f"{MAINT}/api/v1/mantenimiento/reglas",
        json={
            "nombre": "Sobrecalentamiento de motor",
            "tipo_vehiculo": None,
            "metrica": "temperatura_motor_c",
            "umbral": 105,
            "comparador": "mayor",
            "prioridad": 1,
        },
        timeout=5,
    )
    r.raise_for_status()
    print("   regla:", r.json()["id"])

    paso(3, "Tracking (simulado): publicando telemetry.aggregated con 112 °C")
    conexion = pika.BlockingConnection(pika.URLParameters(AMQP))
    canal = conexion.channel()
    canal.exchange_declare(EXCHANGE_EVENTOS, exchange_type="topic", durable=True)
    evento = {
        "event_id": str(uuid.uuid4()),
        "event_type": "telemetry.aggregated",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "producer": "tracking-service",
        "trace_id": uuid.uuid4().hex,
        "payload": {
            "vehicle_id": vehiculo["id"],
            "lecturas": 30,
            "temperatura_motor_max_c": 112.4,
            "velocidad_promedio_kmh": 61.0,
            "combustible_pct": 42.0,
            "odometro_km": 84250,
        },
    }
    canal.basic_publish(
        exchange=EXCHANGE_EVENTOS,
        routing_key="telemetry.aggregated",
        body=json.dumps(evento).encode(),
        properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
    )
    conexion.close()
    print("   event_id:", evento["event_id"])

    paso(4, "Maintenance: esperando que se abra la alerta…")
    alerta = esperar(
        lambda: next(
            (
                a
                for a in requests.get(
                    f"{MAINT}/api/v1/mantenimiento/alertas?estado=abierta", timeout=5
                ).json()
                if a["vehiculo_id"] == vehiculo["id"]
            ),
            None,
        ),
        "alerta abierta en Maintenance",
    )
    print("   programa:", alerta["id"], "| motivo:", alerta["motivo"])
    if placa in (alerta["motivo"] or ""):
        print(f"   \033[92m✔ el motivo trae la placa {placa}\033[0m: Maintenance se la preguntó")
        print("     a Fleet por REST SÍNCRONO — el evento de telemetría no la traía")
    else:
        print("   \033[93m⚠ el motivo no trae placa: Fleet no respondió, actuó el plan B\033[0m")

    paso(5, "Fleet: esperando que el vehículo pase a 'mantenimiento' por el bus…")
    esperar(
        lambda: requests.get(f"{FLEET}/api/v1/vehiculos/{vehiculo['id']}", timeout=5).json()["estado"]
        == "mantenimiento",
        "vehículo en estado mantenimiento",
    )
    print("   estado actual: mantenimiento  ✔ el evento cruzó los dos servicios")

    paso(6, "Fleet: el vehículo ya no aparece entre los disponibles")
    disponibles = requests.get(f"{FLEET}/api/v1/vehiculos/disponibles", timeout=5).json()
    assert vehiculo["id"] not in [v["id"] for v in disponibles], "seguía apareciendo como disponible"
    print("   confirmado: Routing ya no puede asignarle carga")

    paso(7, "Maintenance: registrando la intervención en taller")
    r = requests.post(
        f"{MAINT}/api/v1/mantenimiento/intervenciones",
        json={
            "programa_id": alerta["id"],
            "realizado_en": datetime.now(timezone.utc).isoformat(),
            "costo": 1850000,
            "taller": "Taller Central Montería",
            "km_al_servicio": 84300,
            "notas": "Cambio de termostato y purga del sistema de refrigeración",
        },
        timeout=5,
    )
    r.raise_for_status()
    print("   intervención:", r.json()["id"])

    paso(8, "Fleet: esperando que el vehículo vuelva a 'disponible'…")
    esperar(
        lambda: requests.get(f"{FLEET}/api/v1/vehiculos/{vehiculo['id']}", timeout=5).json()["estado"]
        == "disponible",
        "vehículo de vuelta en disponible",
    )
    print("   estado actual: disponible  ✔ ciclo completo")

    paso(9, "Maintenance: siguiente ciclo preventivo programado automáticamente")
    programa = requests.get(
        f"{MAINT}/api/v1/mantenimiento/vehiculo/{vehiculo['id']}/programa", timeout=5
    ).json()
    preventivo = [p for p in programa if p["origen"] == "preventivo"]
    print("   próximo preventivo:", preventivo[0]["fecha_prevista"], "| km:", preventivo[0]["km_previsto"])

    # ------------------------------------------------------------------
    # COMUNICACIÓN SÍNCRONA: Maintenance como cliente REST de Fleet
    # ------------------------------------------------------------------
    print("\n\033[95m─── COMUNICACIÓN SÍNCRONA (REST) ───\033[0m")

    paso(10, "Maintenance: ficha combinada del vehículo (consulta a Fleet en vivo)")
    ficha = requests.get(
        f"{MAINT}/api/v1/mantenimiento/vehiculo/{vehiculo['id']}/ficha", timeout=10
    ).json()
    if ficha["fuente"] != "fleet":
        print(f"\033[91mFALLO:\033[0m Maintenance no pudo consultar a Fleet ({ficha['detalle_consulta']})")
        sys.exit(1)
    print("   fuente:", ficha["fuente"], "| placa:", ficha["vehiculo"]["placa"])
    print("   tipo:", ficha["vehiculo"]["tipo"], "| estado:", ficha["vehiculo"]["estado"])
    print(f"   historial de mantenimiento: {len(ficha['programa'])} registro(s)")
    print("   ✔ un solo endpoint unió datos de DOS bases de datos distintas")

    paso(11, "Regla POR TIPO de vehículo: lo que la llamada síncrona hace posible")
    placa_t = f"TRC{uuid.uuid4().hex[:3].upper()}"
    r = requests.post(
        f"{FLEET}/api/v1/vehiculos",
        json={
            "placa": placa_t,
            "tipo": "tractomula",
            "capacidad_kg": 34000,
            "capacidad_m3": 90,
            "anio": 2019,
            "vencimiento_seguro": str(date.today() + timedelta(days=300)),
            "certificado_hazmat": True,
            "zona_operacion": "montería",
            "km_actual": 310000,
        },
        timeout=5,
    )
    r.raise_for_status()
    tractomula = r.json()

    requests.post(
        f"{MAINT}/api/v1/mantenimiento/reglas",
        json={
            "nombre": "Horas de motor tractomula",
            "tipo_vehiculo": "tractomula",  # <- solo aplica a tractomulas
            "metrica": "horas_motor",
            "umbral": 500,
            "comparador": "mayor",
            "prioridad": 3,
        },
        timeout=5,
    ).raise_for_status()

    conexion = pika.BlockingConnection(pika.URLParameters(AMQP))
    canal = conexion.channel()
    canal.exchange_declare(EXCHANGE_EVENTOS, exchange_type="topic", durable=True)
    evento_t = {
        "event_id": str(uuid.uuid4()),
        "event_type": "telemetry.aggregated",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "producer": "tracking-service",
        "trace_id": uuid.uuid4().hex,
        # OJO: el evento NO trae "tipo_vehiculo". Sin la llamada síncrona a
        # Fleet, Maintenance jamás sabría que esto es una tractomula y la regla
        # por tipo nunca dispararía.
        "payload": {
            "vehicle_id": tractomula["id"],
            "horas_motor": 640,
            "odometro_km": 310500,
        },
    }
    canal.basic_publish(
        exchange=EXCHANGE_EVENTOS,
        routing_key="telemetry.aggregated",
        body=json.dumps(evento_t).encode(),
        properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
    )
    conexion.close()
    print(f"   publicada telemetría de {placa_t} SIN el campo 'tipo_vehiculo'")

    alerta_t = esperar(
        lambda: next(
            (
                a
                for a in requests.get(
                    f"{MAINT}/api/v1/mantenimiento/alertas?estado=abierta", timeout=5
                ).json()
                if a["vehiculo_id"] == tractomula["id"]
            ),
            None,
        ),
        "alerta por regla de tipo tractomula",
    )
    print("   motivo:", alerta_t["motivo"])
    print("   ✔ Maintenance preguntó el tipo a Fleet y aplicó la regla específica")

    paso(12, "Vehículo inexistente: validación gracias a la consulta síncrona")
    fantasma = uuid.uuid4()
    r = requests.get(f"{MAINT}/api/v1/mantenimiento/vehiculo/{fantasma}/ficha", timeout=10)
    print("   HTTP", r.status_code, "->", r.json().get("detail"))
    if r.status_code != 404:
        print("\033[91mFALLO:\033[0m se esperaba 404 para un vehículo que Fleet no conoce")
        sys.exit(1)
    print("   ✔ Fleet es la fuente de verdad; Maintenance no inventa vehículos")

    paso(13, "Estado de la dependencia síncrona y del circuit breaker")
    dep = requests.get(f"{MAINT}/api/v1/mantenimiento/dependencias", timeout=10).json()
    cb = dep["circuit_breaker"]
    print("   Fleet alcanzable:", dep["fleet"]["alcanzable"])
    print(f"   circuito: {cb['estado']} ({cb['fallos_en_ventana']}/{cb['umbral_fallos']} fallos)")
    pol = dep["politica"]
    print(f"   política: timeout {pol['timeout_segundos']}s · {pol['max_intentos']} intentos")
    print(f"             backoff {pol['backoff_segundos']}s + jitter")

    print("\n\033[92mDEMO OK — los dos microservicios funcionan e interoperan.\033[0m")
    print("\033[92mASÍNCRONO:\033[0m eventos por RabbitMQ (outbox, idempotencia, DLQ)")
    print("\033[92mSÍNCRONO :\033[0m REST de Maintenance a Fleet (timeout, reintentos, circuit breaker)")


if __name__ == "__main__":
    main()
