"""Listados del catálogo: GET /vehiculos y GET /conductores.

Estos dos endpoints NO están en la ficha 3.2 del documento. Se añaden porque
`/vehiculos/disponibles` filtra por definición `estado == disponible`, y un panel
de operaciones tiene que poder ver — y devolver a servicio — justo los vehículos
que NO están disponibles.
"""

BASE = {
    "tipo": "van",
    "capacidad_kg": 1200,
    "capacidad_m3": 8,
    "anio": 2023,
    "vencimiento_seguro": "2030-01-01",
}


def _crear(cliente, placa, **extra):
    respuesta = cliente.post("/api/v1/vehiculos", json={**BASE, "placa": placa, **extra})
    assert respuesta.status_code == 201
    return respuesta.json()


def test_listado_vacio_devuelve_total_cero(cliente):
    cuerpo = cliente.get("/api/v1/vehiculos").json()
    assert cuerpo == {"total": 0, "limite": 50, "desplazamiento": 0, "items": []}


def test_listado_incluye_vehiculos_no_disponibles(cliente):
    """La diferencia real con /disponibles: este listado sí los ve."""
    v = _crear(cliente, "AAA111")
    cliente.patch(
        f"/api/v1/vehiculos/{v['id']}/estado",
        json={"estado": "mantenimiento", "motivo": "alerta de temperatura"},
    )

    assert cliente.get("/api/v1/vehiculos/disponibles").json() == []

    cuerpo = cliente.get("/api/v1/vehiculos").json()
    assert cuerpo["total"] == 1
    assert cuerpo["items"][0]["estado"] == "mantenimiento"


def test_filtro_por_estado(cliente):
    v = _crear(cliente, "AAA111")
    _crear(cliente, "BBB222")
    cliente.patch(
        f"/api/v1/vehiculos/{v['id']}/estado",
        json={"estado": "fuera_servicio", "motivo": "incidencia en ruta"},
    )

    cuerpo = cliente.get("/api/v1/vehiculos?estado=fuera_servicio").json()
    assert cuerpo["total"] == 1
    assert cuerpo["items"][0]["placa"] == "AAA111"


def test_filtros_tipo_zona_y_placa_parcial(cliente):
    _crear(cliente, "AAA111", tipo="moto", capacidad_kg=120, capacidad_m3=1, zona_operacion="cereté")
    _crear(cliente, "AAB222", zona_operacion="montería")

    assert cliente.get("/api/v1/vehiculos?tipo=moto").json()["total"] == 1
    assert cliente.get("/api/v1/vehiculos?zona=cereté").json()["total"] == 1
    # búsqueda parcial e insensible a mayúsculas sobre la placa
    assert cliente.get("/api/v1/vehiculos?placa=aa").json()["total"] == 2
    assert cliente.get("/api/v1/vehiculos?placa=AAB").json()["total"] == 1


def test_paginacion_devuelve_total_completo_y_pagina_corta(cliente):
    for i in range(5):
        _crear(cliente, f"PAG{i:03d}")

    cuerpo = cliente.get("/api/v1/vehiculos?limite=2&desplazamiento=2").json()
    assert cuerpo["total"] == 5  # el total NO es el tamaño de la página
    assert len(cuerpo["items"]) == 2
    assert cuerpo["items"][0]["placa"] == "PAG002"  # ordenado por placa


def test_estado_invalido_devuelve_422(cliente):
    assert cliente.get("/api/v1/vehiculos?estado=inventado").status_code == 422


def test_limite_fuera_de_rango_devuelve_422(cliente):
    assert cliente.get("/api/v1/vehiculos?limite=500").status_code == 422


def test_listado_de_conductores_trae_categorias(cliente):
    cliente.post(
        "/api/v1/conductores",
        json={
            "nombre": "Kevin Ayazo",
            "numero_licencia": "LIC-001",
            "certificacion_hazmat": True,
            "categorias": ["c2", "C3"],
        },
    )
    cliente.post(
        "/api/v1/conductores",
        json={"nombre": "Ana Ruiz", "numero_licencia": "LIC-002", "categorias": ["C1"]},
    )

    cuerpo = cliente.get("/api/v1/conductores").json()
    assert [c["nombre"] for c in cuerpo] == ["Ana Ruiz", "Kevin Ayazo"]  # orden alfabético
    kevin = cuerpo[1]
    assert kevin["categorias"] == ["C2", "C3"]  # normalizadas a mayúsculas al crear


def test_filtro_de_conductores_por_nombre_parcial(cliente):
    cliente.post(
        "/api/v1/conductores",
        json={"nombre": "Kevin Ayazo", "numero_licencia": "LIC-001", "categorias": []},
    )
    cliente.post(
        "/api/v1/conductores",
        json={"nombre": "Ana Ruiz", "numero_licencia": "LIC-002", "categorias": []},
    )

    assert len(cliente.get("/api/v1/conductores?nombre=ayazo").json()) == 1
    assert cliente.get("/api/v1/conductores?nombre=zzz").json() == []
