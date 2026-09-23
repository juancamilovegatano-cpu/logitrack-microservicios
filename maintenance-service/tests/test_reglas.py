"""Evaluación de umbrales: el núcleo de negocio de Maintenance."""

from app import crud
from app.models import Regla


def _regla(db, **campos) -> Regla:
    base = {
        "nombre": "regla",
        "tipo_vehiculo": None,
        "metrica": "temperatura_motor_c",
        "umbral": 105,
        "comparador": "mayor",
        "prioridad": 3,
    }
    base.update(campos)
    regla = Regla(**base)
    db.add(regla)
    db.commit()
    return regla


# ------------------------------------------------------------ comparador


def test_comparador_mayor(db):
    regla = _regla(db, umbral=105, comparador="mayor")
    assert crud.dispara(regla, 112.4) is True
    assert crud.dispara(regla, 104.9) is False
    assert crud.dispara(regla, 105.0) is False  # el umbral exacto NO dispara


def test_comparador_menor(db):
    """Sin el comparador, un umbral como 'combustible por debajo de 10 %'
    sería imposible de expresar."""
    regla = _regla(db, metrica="nivel_combustible_pct", umbral=10, comparador="menor")
    assert crud.dispara(regla, 8.0) is True
    assert crud.dispara(regla, 12.0) is False
    assert crud.dispara(regla, 10.0) is False


# --------------------------------------------------- filtro por tipo


def test_regla_sin_tipo_aplica_a_todos(db):
    _regla(db, nombre="general", tipo_vehiculo=None)
    assert len(crud.reglas_aplicables(db, "temperatura_motor_c", "tractomula")) == 1
    assert len(crud.reglas_aplicables(db, "temperatura_motor_c", "moto")) == 1
    assert len(crud.reglas_aplicables(db, "temperatura_motor_c", None)) == 1


def test_regla_por_tipo_solo_aplica_a_ese_tipo(db):
    """Esta es la regla que la llamada REST síncrona a Fleet hace posible:
    sin conocer el tipo del vehículo, nunca dispararía."""
    _regla(db, nombre="solo tractomulas", metrica="horas_motor", tipo_vehiculo="tractomula")

    assert len(crud.reglas_aplicables(db, "horas_motor", "tractomula")) == 1
    assert crud.reglas_aplicables(db, "horas_motor", "moto") == []
    # sin tipo conocido, las reglas específicas quedan fuera
    assert crud.reglas_aplicables(db, "horas_motor", None) == []


def test_tipo_conocido_trae_las_generales_y_las_suyas(db):
    _regla(db, nombre="general", metrica="horas_motor", tipo_vehiculo=None)
    _regla(db, nombre="tractomula", metrica="horas_motor", tipo_vehiculo="tractomula")
    assert len(crud.reglas_aplicables(db, "horas_motor", "tractomula")) == 2
    assert len(crud.reglas_aplicables(db, "horas_motor", "van")) == 1


def test_regla_inactiva_no_aplica(db):
    _regla(db, nombre="apagada", activa=False)
    assert crud.reglas_aplicables(db, "temperatura_motor_c", None) == []


def test_las_reglas_salen_ordenadas_por_prioridad(db):
    _regla(db, nombre="baja", prioridad=5)
    _regla(db, nombre="urgente", prioridad=1)
    nombres = [r.nombre for r in crud.reglas_aplicables(db, "temperatura_motor_c", None)]
    assert nombres == ["urgente", "baja"]


# ------------------------------------------------------------- API REST


def test_metrica_desconocida_devuelve_422(cliente):
    respuesta = cliente.post(
        "/api/v1/mantenimiento/reglas",
        json={
            "nombre": "inventada",
            "metrica": "color_del_capo",
            "umbral": 1,
            "comparador": "mayor",
            "prioridad": 3,
        },
    )
    assert respuesta.status_code == 422


def test_codigo_obd2_no_se_puede_configurar(cliente):
    """Defecto 3.3: codigo_obd2 se ofrecía en la UI pero no está en CAMPOS.

    El payload de telemetry.aggregated trae `codigos_obd2` como LISTA de
    códigos ("P0420"), y las reglas comparan umbrales numéricos
    (dispara() hace float(valor)): una regla con esa métrica nunca podría
    disparar — a añadirla a CAMPOS, float(lista) revienta y manda cada
    evento de telemetría a la DLQ. Por eso se quita: ahora el intento de
    configurarla responde 422 (un aviso) en vez de guardar en silencio una
    regla que no hará nada.
    """
    respuesta = cliente.post(
        "/api/v1/mantenimiento/reglas",
        json={
            "nombre": "codigos obd2",
            "metrica": "codigo_obd2",
            "umbral": 1,
            "comparador": "mayor",
            "prioridad": 3,
        },
    )
    assert respuesta.status_code == 422


def test_prioridad_fuera_de_rango_devuelve_422(cliente):
    respuesta = cliente.post(
        "/api/v1/mantenimiento/reglas",
        json={
            "nombre": "prioridad mala",
            "metrica": "horas_motor",
            "umbral": 1,
            "comparador": "mayor",
            "prioridad": 99,
        },
    )
    assert respuesta.status_code == 422


def test_proximos_limita_la_ventana_a_365_dias(cliente):
    assert cliente.get("/api/v1/mantenimiento/proximos?dias=400").status_code == 422
    assert cliente.get("/api/v1/mantenimiento/proximos?dias=0").status_code == 422
    assert cliente.get("/api/v1/mantenimiento/proximos?dias=90").status_code == 200
