"""Configuración común de las pruebas de Maintenance Service.

Se prueba contra un PostgreSQL REAL (los modelos usan UUID, JSONB y ENUM de
PostgreSQL) y con el bus apagado: lo que se verifica es que las filas del
outbox se escriban en la transacción correcta.

Las llamadas REST a Fleet se sustituyen por dobles en cada prueba, para poder
forzar los casos que no se pueden provocar a voluntad contra un servicio real:
timeouts, 404 y el circuito abierto.

    docker compose up -d maintenance-db
    pytest
"""

import os

# Host y puerto por variable de entorno, con el defecto de ESTE servicio:
# Maintenance vive en el 5433 (su base está ahí, no en el 5432 de Fleet);
# hasta esta corrección los tests de Maintenance se conectaban por error al
# 5432 y usaban la test_db de Fleet por accidente.
_HOST = os.environ.get("TEST_DB_HOST", "localhost")
_PUERTO = os.environ.get("TEST_DB_PUERTO", "5433")
_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "logitrack")
os.environ.setdefault(
    "DATABASE_URL",
    f"postgresql+psycopg2://logitrack:{_PASSWORD}@{_HOST}:{_PUERTO}/test_db",
)
os.environ["EVENTS_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import models  # noqa: E402, F401  - registra las tablas en el metadata
from app.database import (  # noqa: E402
    Base,
    SessionLocal,
    aplicar_ajustes_pendientes,
    engine,
)
from app.main import app  # noqa: E402


def _crear_base_si_falta():
    """Un repo recién clonado no tiene `test_db` en el 5433: la crea si falta.

    Conecta al catálogo `postgres` del MISMO servidor al que apunta la URL de
    los tests y ejecuta CREATE DATABASE solo si el nombre no existe. Así
    `python -m pytest` funciona con el compose arriba y nada más (defecto 2.3).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    url = make_url(os.environ["DATABASE_URL"])
    motor_admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with motor_admin.connect() as conexion:
            existe = conexion.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :nombre"),
                {"nombre": url.database},
            ).scalar()
            if not existe:
                conexion.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        motor_admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def esquema():
    _crear_base_si_falta()
    Base.metadata.create_all(engine)
    # test_db suele existir de antes: create_all no le añade columnas nuevas,
    # así que aplicamos los mismos ajustes que aplicaría el arranque real.
    aplicar_ajustes_pendientes(engine)
    yield


@pytest.fixture(autouse=True)
def base_limpia():
    yield
    tablas = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    with engine.begin() as conexion:
        conexion.execute(text(f"TRUNCATE {tablas} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def breaker_limpio():
    """El circuito es estado global del proceso: se reinicia entre pruebas."""
    from app.clients import fleet

    fleet.breaker.registrar_exito()
    yield
    fleet.breaker.registrar_exito()


@pytest.fixture
def db():
    sesion = SessionLocal()
    try:
        yield sesion
    finally:
        sesion.close()


@pytest.fixture
def cliente():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def regla_temperatura(cliente):
    return cliente.post(
        "/api/v1/mantenimiento/reglas",
        json={
            "nombre": "Sobrecalentamiento de motor",
            "tipo_vehiculo": None,
            "metrica": "temperatura_motor_c",
            "umbral": 105,
            "comparador": "mayor",
            "prioridad": 1,
        },
    ).json()
