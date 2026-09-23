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

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg2://logitrack:logitrack@localhost:5432/test_db"
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


@pytest.fixture(scope="session", autouse=True)
def esquema():
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
