"""API de vehículos: validaciones, errores HTTP y filtros de disponibilidad."""

import uuid


def test_crear_vehiculo_devuelve_201_y_location(cliente):
    respuesta = cliente.post(
        "/api/v1/vehiculos",
        json={
            "placa": "XYZ789",
            "tipo": "furgon",
            "capacidad_kg": 3500,
            "capacidad_m3": 18,
            "anio": 2022,
            "vencimiento_seguro": "2030-01-01",
        },
        follow_redirects=False,
    )
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["placa"] == "XYZ789"
    assert cuerpo["estado"] == "disponible"  # estado inicial por defecto
    assert respuesta.headers["Location"] == f"/api/v1/vehiculos/{cuerpo['id']}"


def test_placa_duplicada_devuelve_409(cliente, vehiculo):
    respuesta = cliente.post(
        "/api/v1/vehiculos",
        json={
            "placa": vehiculo["placa"],
            "tipo": "van",
            "capacidad_kg": 1200,
            "capacidad_m3": 8,
            "anio": 2023,
            "vencimiento_seguro": "2030-01-01",
        },
    )
    assert respuesta.status_code == 409
    assert respuesta.json()["detail"]["error"] == "placa_duplicada"


def test_capacidad_invalida_devuelve_422(cliente):
    """La validación de entrada corta antes de tocar la base de datos."""
    respuesta = cliente.post(
        "/api/v1/vehiculos",
        json={
            "placa": "BAD001",
            "tipo": "van",
            "capacidad_kg": -5,  # el esquema exige > 0
            "capacidad_m3": 8,
            "anio": 2023,
            "vencimiento_seguro": "2030-01-01",
        },
    )
    assert respuesta.status_code == 422


def test_tipo_desconocido_devuelve_422(cliente):
    respuesta = cliente.post(
        "/api/v1/vehiculos",
        json={
            "placa": "BAD002",
            "tipo": "helicoptero",  # no está en el Literal
            "capacidad_kg": 100,
            "capacidad_m3": 1,
            "anio": 2023,
            "vencimiento_seguro": "2030-01-01",
        },
    )
    assert respuesta.status_code == 422


def test_vehiculo_inexistente_devuelve_404(cliente):
    respuesta = cliente.get(f"/api/v1/vehiculos/{uuid.uuid4()}")
    assert respuesta.status_code == 404
    assert respuesta.json()["detail"]["error"] == "vehiculo_no_encontrado"


def test_id_mal_formado_devuelve_422(cliente):
    respuesta = cliente.get("/api/v1/vehiculos/no-es-un-uuid")
    assert respuesta.status_code == 422


def test_disponibles_filtra_por_zona_y_capacidad(cliente, vehiculo):
    assert vehiculo["id"] in [
        v["id"] for v in cliente.get("/api/v1/vehiculos/disponibles?zona=montería").json()
    ]
    # zona que no es la suya
    assert cliente.get("/api/v1/vehiculos/disponibles?zona=sincelejo").json() == []
    # capacidad por encima de la que tiene
    assert cliente.get("/api/v1/vehiculos/disponibles?capacidad_min_kg=99000").json() == []


def test_disponibles_excluye_seguro_vencido(cliente):
    """Un seguro vencido inhabilita el vehículo aunque su estado diga 'disponible'."""
    creado = cliente.post(
        "/api/v1/vehiculos",
        json={
            "placa": "OLD001",
            "tipo": "van",
            "capacidad_kg": 1200,
            "capacidad_m3": 8,
            "anio": 2015,
            "vencimiento_seguro": "2020-01-01",  # vencido
        },
    ).json()
    assert creado["estado"] == "disponible"
    disponibles = cliente.get("/api/v1/vehiculos/disponibles").json()
    assert creado["id"] not in [v["id"] for v in disponibles]


def test_vehiculo_en_mantenimiento_sale_de_disponibles(cliente, vehiculo):
    cliente.patch(
        f"/api/v1/vehiculos/{vehiculo['id']}/estado",
        json={"estado": "mantenimiento", "motivo": "Sobrecalentamiento detectado"},
    )
    disponibles = cliente.get("/api/v1/vehiculos/disponibles").json()
    assert vehiculo["id"] not in [v["id"] for v in disponibles]


def test_motivo_demasiado_corto_devuelve_422(cliente, vehiculo):
    respuesta = cliente.patch(
        f"/api/v1/vehiculos/{vehiculo['id']}/estado",
        json={"estado": "en_ruta", "motivo": "x"},  # el esquema exige 3 caracteres
    )
    assert respuesta.status_code == 422


def test_zona_operacion_larga_devuelve_422(cliente):
    """Defecto 4.2: la columna es String(60) pero el schema no impone
    max_length: la cadena llegaba a PostgreSQL y salía un 500 en vez de un 422."""
    respuesta = cliente.post(
        "/api/v1/vehiculos",
        json={
            "placa": "ZON100",
            "tipo": "van",
            "capacidad_kg": 1200,
            "capacidad_m3": 8,
            "anio": 2023,
            "vencimiento_seguro": "2030-01-01",
            "zona_operacion": "x" * 61,
        },
    )
    assert respuesta.status_code == 422
