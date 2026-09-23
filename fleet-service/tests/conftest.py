"""Configuración común de las pruebas de Fleet Service.

Se prueba contra un PostgreSQL REAL, no contra SQLite ni dobles: los modelos
usan tipos propios de PostgreSQL (UUID, JSONB, ENUM) y una prueba que no los
ejercita no demuestra nada sobre el esquema que se despliega.

    docker compose up -d fleet-db
    pytest

El bus de eventos queda apagado (EVENTS_ENABLED=false): las pruebas verifican
que las filas del OUTBOX se escriban en la transacción correcta, que es la
garantía que importa. Que RabbitMQ entregue el mensaje es responsabilidad de
RabbitMQ, no de este código.
"""

import os

# Host y puerto por variable de entorno, con el defecto de ESTE servicio:
# Fleet vive en el 5432; Maintenance en el 5433 (una base por servicio).
_HOST = os.environ.get("TEST_DB_HOST", "localhost")
_PUERTO = os.environ.get("TEST_DB_PUERTO", "5432")
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
    """Un repo recién clonado no tiene `test_db`: la crea si hace falta.

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
    """Cada prueba arranca con las tablas vacías: ninguna depende de otra."""
    yield
    tablas = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    with engine.begin() as conexion:
        conexion.execute(text(f"TRUNCATE {tablas} RESTART IDENTITY CASCADE"))


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
def vehiculo(cliente):
    """Un vehículo recién creado, disponible."""
    respuesta = cliente.post(
        "/api/v1/vehiculos",
        json={
            "placa": "TST001",
            "tipo": "camion_rigido",
            "capacidad_kg": 8000,
            "capacidad_m3": 30,
            "anio": 2021,
            "vencimiento_seguro": "2030-01-01",
            "refrigerado": True,
            "zona_operacion": "montería",
            "km_actual": 84000,
        },
    )
    assert respuesta.status_code == 201
    return respuesta.json()
