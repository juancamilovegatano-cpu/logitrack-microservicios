#!/usr/bin/env python3
"""Carga datos iniciales: 6 vehículos, 3 conductores y 4 reglas de mantenimiento."""

import os
from datetime import date, timedelta

import requests

FLEET = os.getenv("FLEET_URL", "http://localhost:8001")
MAINT = os.getenv("MAINT_URL", "http://localhost:8006")  # 8002 es de tracking-service

VEHICULOS = [
    ("ABC123", "tractomula", 34000, 90, 2019, False, True, "montería"),
    ("DEF456", "camion_rigido", 9000, 32, 2021, True, False, "montería"),
    ("GHI789", "furgon", 3500, 18, 2022, True, False, "sincelejo"),
    ("JKL012", "van", 1200, 8, 2023, False, False, "montería"),
    ("MNO345", "camion_rigido", 8500, 30, 2018, False, True, "cereté"),
    ("PQR678", "moto", 120, 0.5, 2024, False, False, "montería"),
]

CONDUCTORES = [
    ("Kevin Ayazo", "LIC-001", True, ["C2", "C3"]),
    ("Keyner Madrid", "LIC-002", False, ["C2"]),
    ("Juan Vega", "LIC-003", True, ["C3"]),
]

REGLAS = [
    ("Sobrecalentamiento de motor", None, "temperatura_motor_c", 105, "mayor", 1),
    ("Combustible crítico", None, "nivel_combustible_pct", 10, "menor", 2),
    ("Cambio de aceite por kilometraje", None, "km_acumulados", 15000, "mayor", 4),
    ("Horas de motor tractomula", "tractomula", "horas_motor", 500, "mayor", 3),
]


def main():
    for placa, tipo, kg, m3, anio, refrigerado, hazmat, zona in VEHICULOS:
        r = requests.post(
            f"{FLEET}/api/v1/vehiculos",
            json={
                "placa": placa,
                "tipo": tipo,
                "capacidad_kg": kg,
                "capacidad_m3": m3,
                "anio": anio,
                "vencimiento_seguro": str(date.today() + timedelta(days=300)),
                "refrigerado": refrigerado,
                "certificado_hazmat": hazmat,
                "zona_operacion": zona,
            },
            timeout=5,
        )
        # 409 = la placa es unica y ya estaba: no es un error, es idempotencia.
        detalle = "ya existía" if r.status_code == 409 else r.status_code
        print(f"vehiculo {placa}: {detalle}")

    for nombre, licencia, hazmat, categorias in CONDUCTORES:
        r = requests.post(
            f"{FLEET}/api/v1/conductores",
            json={
                "nombre": nombre,
                "numero_licencia": licencia,
                "certificacion_hazmat": hazmat,
                "categorias": categorias,
            },
            timeout=5,
        )
        # 409 = la licencia es unica y ya existía: idempotencia, no error.
        detalle = "ya existía" if r.status_code == 409 else r.status_code
        print(f"conductor {nombre}: {detalle}")

    # Idempotencia (defecto 2.5): las reglas NO tienen nombre único, así que
    # el POST siempre creaba una fila nueva y cada corrida añadía cuatro más
    # (a la tercera, la misma métrica disparaba alertas duplicadas con
    # regla_id distinto). Se busca cada regla por nombre antes de crearla.
    existentes = {
        regla["nombre"]
        for regla in requests.get(f"{MAINT}/api/v1/mantenimiento/reglas", timeout=5).json()
    }
    for nombre, tipo_veh, metrica, umbral, comparador, prioridad in REGLAS:
        if nombre in existentes:
            print(f"regla {nombre}: ya existía")
            continue
        r = requests.post(
            f"{MAINT}/api/v1/mantenimiento/reglas",
            json={
                "nombre": nombre,
                "tipo_vehiculo": tipo_veh,
                "metrica": metrica,
                "umbral": umbral,
                "comparador": comparador,
                "prioridad": prioridad,
            },
            timeout=5,
        )
        print(f"regla {nombre}: {r.status_code}")


if __name__ == "__main__":
    main()
