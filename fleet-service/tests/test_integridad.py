"""Defecto 4.3: no todo IntegrityError es un conflicto de unicidad.

Un 409 dice "tu petición choca con el estado actual del sistema". Eso solo
es verdad para SQLSTATE 23505 (unique_violation): una violación de clave
ajena o de una regla CHECK es un fallo del servidor y debe salir como 500,
no disfrazarse de conflicto del cliente.

Los routers se invocan aquí directamente con un error de base simulado,
porque los dos caminos (23505 y el resto) no se pueden provocar a voluntad
contra el PostgreSQL real: solo uno de ellos es alcanzable por la API.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from sqlalchemy.exc import IntegrityError

from app import schemas
from app.routers import conductores, vehiculos


class _ErrorPG(Exception):
    """Parecido a un error de psycopg2: de él solo se lee su pgcode."""

    def __init__(self, pgcode: str):
        super().__init__(pgcode)
        self.pgcode = pgcode


def _db_que_falla_en_commit(pgcode: str):
    db = SimpleNamespace(
        add=lambda obj: None,
        refresh=lambda obj: None,
        rollback=lambda: None,
    )

    def commit():
        raise IntegrityError("INSERT", {}, _ErrorPG(pgcode))

    db.commit = commit
    return db


def _vehiculo():
    return schemas.VehiculoCrear(
        placa="INT001",
        tipo="van",
        capacidad_kg=1200,
        capacidad_m3=8,
        anio=2023,
        vencimiento_seguro="2030-01-01",
    )


def _conductor():
    return schemas.ConductorCrear(
        nombre="Ana Ruiz", numero_licencia="LIC-900", categorias=["C2"]
    )


def test_en_vehiculos_solo_el_23505_es_409():
    with pytest.raises(HTTPException) as exc:
        vehiculos.crear(_vehiculo(), Response(), _db_que_falla_en_commit("23505"))
    assert exc.value.status_code == 409


def test_en_vehiculos_un_integrity_error_que_no_es_unicidad_se_propaga():
    """Antes: también devolvía 409 'placa_duplicada', aunque el código fuera 23503."""
    with pytest.raises(IntegrityError):
        vehiculos.crear(_vehiculo(), Response(), _db_que_falla_en_commit("23503"))


def test_en_conductores_solo_el_23505_es_409():
    with pytest.raises(HTTPException) as exc:
        conductores.crear(_conductor(), _db_que_falla_en_commit("23505"))
    assert exc.value.status_code == 409


def test_en_conductores_un_integrity_error_que_no_es_unicidad_se_propaga():
    with pytest.raises(IntegrityError):
        conductores.crear(_conductor(), _db_que_falla_en_commit("23502"))
