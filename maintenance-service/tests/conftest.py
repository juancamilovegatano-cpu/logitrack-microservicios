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

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg2://logitrack:logitrack@localhost:5432/test_db"
)
os.environ["EVENTS_ENABLED"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import models  # noqa: E402, F401  - registra las tablas en el metadata
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def esquema():
    Base.metadata.create_all(engine)
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
