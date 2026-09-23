"""Consumidor de telemetría: donde se cruzan los dos estilos de comunicación.

El evento llega por el bus (ASÍNCRONO) y, antes de evaluar las reglas, el
consumidor le pregunta a Fleet quién es ese vehículo (SÍNCRONO).

Se cubren los tres desenlaces de esa consulta:
    ok             -> se enriquece la alerta y aplican las reglas por tipo
    no_encontrado  -> el vehículo no existe: no se abre nada
    no_disponible  -> PLAN B: se evalúa con lo que trae el evento
"""

import uuid

import pytest
from sqlalchemy import select

from app.clients.fleet import RespuestaFleet
from app.events import consumer
from app.models import EventoProcesado, OutboxEvento, ProgramaMantenimiento, Regla

VEHICULO_ID = str(uuid.uuid4())


@pytest.fixture
def regla_general(db):
    regla = Regla(
        nombre="Sobrecalentamiento de motor",
        tipo_vehiculo=None,
        metrica="temperatura_motor_c",
        umbral=105,
        comparador="mayor",
        prioridad=1,
    )
    db.add(regla)
    db.commit()
    return regla


@pytest.fixture
def regla_tractomula(db):
    regla = Regla(
        nombre="Horas de motor tractomula",
        tipo_vehiculo="tractomula",
        metrica="horas_motor",
        umbral=500,
        comparador="mayor",
        prioridad=3,
    )
    db.add(regla)
    db.commit()
    return regla


def _telemetria(event_id=None, **datos) -> dict:
    """Sobre canónico y nombres de campo del contrato de Tracking."""
    cuerpo = {"vehicle_id": VEHICULO_ID}
    cuerpo.update(datos)
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": "telemetry.aggregated",
        "occurred_at": "2026-01-01T00:00:00+00:00",
        "producer": "tracking-service",
        "trace_id": uuid.uuid4().hex,
        "payload": cuerpo,
    }


def _fleet_responde(monkeypatch, respuesta: RespuestaFleet):
    monkeypatch.setattr(consumer.fleet, "obtener_vehiculo", lambda _id: respuesta)


def _ok(tipo="camion_rigido", placa="ABC123", km=84000) -> RespuestaFleet:
    return RespuestaFleet(
        "ok", vehiculo={"id": VEHICULO_ID, "placa": placa, "tipo": tipo, "km_actual": km}
    )


# ----------------------------------------------------- Fleet responde bien


def test_umbral_superado_abre_la_alerta(db, monkeypatch, regla_general):
    _fleet_responde(monkeypatch, _ok())
    consumer.manejar(_telemetria(temperatura_motor_max_c=112.4))

    programas = db.scalars(select(ProgramaMantenimiento)).all()
    assert len(programas) == 1
    assert programas[0].origen == "alerta"
    assert programas[0].estado == "pendiente"


def test_la_alerta_se_enriquece_con_la_placa_que_dio_fleet(db, monkeypatch, regla_general):
    """El evento de telemetría no trae la placa: sale de la consulta síncrona."""
    _fleet_responde(monkeypatch, _ok(placa="XYZ789"))
    consumer.manejar(_telemetria(temperatura_motor_max_c=112.4))

    programa = db.scalars(select(ProgramaMantenimiento)).one()
    assert "XYZ789" in programa.motivo

    evento = db.scalars(select(OutboxEvento)).one()
    assert evento.tipo == "maintenance.alert"
    assert evento.payload["placa"] == "XYZ789"


def test_el_km_de_fleet_gana_sobre_el_del_evento(db, monkeypatch, regla_general):
    _fleet_responde(monkeypatch, _ok(km=99999))
    consumer.manejar(_telemetria(temperatura_motor_max_c=112.4, odometro_km=1))
    assert db.scalars(select(ProgramaMantenimiento)).one().km_previsto == 99999


def test_regla_por_tipo_dispara_gracias_a_la_consulta_sincrona(db, monkeypatch, regla_tractomula):
    """El evento NO trae tipo_vehiculo. Sin preguntarle a Fleet, esta regla
    sería código muerto."""
    _fleet_responde(monkeypatch, _ok(tipo="tractomula"))
    consumer.manejar(_telemetria(horas_motor=640))
    assert len(db.scalars(select(ProgramaMantenimiento)).all()) == 1


def test_regla_de_otro_tipo_no_dispara(db, monkeypatch, regla_tractomula):
    _fleet_responde(monkeypatch, _ok(tipo="moto"))
    consumer.manejar(_telemetria(horas_motor=640))
    assert db.scalars(select(ProgramaMantenimiento)).all() == []


def test_umbral_no_superado_no_abre_nada(db, monkeypatch, regla_general):
    _fleet_responde(monkeypatch, _ok())
    consumer.manejar(_telemetria(temperatura_motor_max_c=90.0))
    assert db.scalars(select(ProgramaMantenimiento)).all() == []
    assert "sin umbrales superados" in db.scalars(select(EventoProcesado)).one().detalle


# -------------------------------------------------------- Fleet dice 404


def test_vehiculo_desconocido_no_abre_alerta(db, monkeypatch, regla_general):
    """Abrir una alerta para un UUID fantasma solo ensucia el calendario."""
    _fleet_responde(monkeypatch, RespuestaFleet("no_encontrado", detalle="no existe"))
    consumer.manejar(_telemetria(temperatura_motor_max_c=112.4))

    assert db.scalars(select(ProgramaMantenimiento)).all() == []
    assert "no reconoce" in db.scalars(select(EventoProcesado)).one().detalle


# ------------------------------------------------- Fleet no responde: plan B


def test_plan_b_abre_la_alerta_igual(db, monkeypatch, regla_general):
    """Con Fleet caído la alerta se abre de todos modos: una alerta sin placa
    es mejor que un motor fundido."""
    _fleet_responde(monkeypatch, RespuestaFleet("no_disponible", detalle="circuito abierto"))
    consumer.manejar(_telemetria(temperatura_motor_max_c=112.4))

    programa = db.scalars(select(ProgramaMantenimiento)).one()
    assert programa.estado == "pendiente"
    assert "vehículo" not in programa.motivo  # sin enriquecer, no hay placa


def test_el_plan_b_queda_registrado(db, monkeypatch, regla_general):
    _fleet_responde(monkeypatch, RespuestaFleet("no_disponible", detalle="timeout"))
    consumer.manejar(_telemetria(temperatura_motor_max_c=112.4))
    assert "degradado" in db.scalars(select(EventoProcesado)).one().detalle


def test_sin_fleet_las_reglas_por_tipo_no_pueden_aplicarse(db, monkeypatch, regla_tractomula):
    """Consecuencia honesta de la degradación: sin el tipo, esa regla no corre."""
    _fleet_responde(monkeypatch, RespuestaFleet("no_disponible", detalle="timeout"))
    consumer.manejar(_telemetria(horas_motor=640))
    assert db.scalars(select(ProgramaMantenimiento)).all() == []


# ------------------------------------------------------------ idempotencia


def test_evento_repetido_no_abre_dos_alertas(db, monkeypatch, regla_general):
    _fleet_responde(monkeypatch, _ok())
    evento = _telemetria(temperatura_motor_max_c=112.4)
    consumer.manejar(evento)
    consumer.manejar(evento)  # reentrega de RabbitMQ

    assert len(db.scalars(select(ProgramaMantenimiento)).all()) == 1
    assert len(db.scalars(select(EventoProcesado)).all()) == 1


def test_dos_lecturas_distintas_no_duplican_la_alerta_abierta(db, monkeypatch, regla_general):
    """event_id distinto, misma regla y mismo vehículo: la alerta ya está
    abierta, no se abre otra."""
    _fleet_responde(monkeypatch, _ok())
    consumer.manejar(_telemetria(temperatura_motor_max_c=112.4))
    consumer.manejar(_telemetria(temperatura_motor_max_c=118.0))

    assert len(db.scalars(select(ProgramaMantenimiento)).all()) == 1
    assert len(db.scalars(select(EventoProcesado)).all()) == 2  # los dos sí se procesaron
