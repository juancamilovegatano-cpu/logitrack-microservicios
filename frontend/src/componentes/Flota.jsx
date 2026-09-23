/**
 * Pestaña Flota — Fleet Service (ficha 3.2).
 *
 * Cubre los cinco endpoints de vehículos: listado del catálogo, consulta de
 * asignables, alta, cambio de estado y ficha individual. El cambio de estado es
 * el que publica vehicle.status_changed por el outbox, así que desde aquí se
 * dispara media cadena de eventos del sistema.
 */

import { useState } from "react";

import { ESTADOS_VEHICULO, TIPOS_VEHICULO, fleet, mantenimiento } from "../api.js";
import {
  Aviso,
  Campo,
  Cargando,
  Error_,
  Etiqueta,
  Id,
  Modal,
  Panel,
  Selector,
  Tabla,
  diasHasta,
  fecha,
  numero,
  useCargar,
} from "../ui.jsx";

const POR_PAGINA = 25;

const VEHICULO_VACIO = {
  placa: "",
  tipo: "camion_rigido",
  capacidad_kg: "",
  capacidad_m3: "",
  anio: new Date().getFullYear(),
  vencimiento_seguro: "",
  refrigerado: false,
  certificado_hazmat: false,
  zona_operacion: "montería",
};

/* ------------------------------------------------------- alta de vehículo */

function FormularioVehiculo({ onCerrar, onCreado }) {
  const [datos, setDatos] = useState(VEHICULO_VACIO);
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);

  const cambiar = (clave) => (evento) => {
    const control = evento.target;
    setDatos((previo) => ({
      ...previo,
      [clave]: control.type === "checkbox" ? control.checked : control.value,
    }));
  };

  const enviar = async (evento) => {
    evento.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      const creado = await fleet.crearVehiculo({
        ...datos,
        capacidad_kg: Number(datos.capacidad_kg),
        capacidad_m3: Number(datos.capacidad_m3),
        anio: Number(datos.anio),
      });
      onCreado(creado);
    } catch (fallo) {
      setError(fallo);
      setEnviando(false);
    }
  };

  return (
    <Modal titulo="Nuevo vehículo" onCerrar={onCerrar}>
      <form onSubmit={enviar}>
        <Error_ error={error} />
        <div className="rejilla dos">
          <Campo etiqueta="Placa" ayuda="Entre 5 y 10 caracteres, única en el sistema">
            <input
              value={datos.placa}
              onChange={cambiar("placa")}
              minLength={5}
              maxLength={10}
              required
              autoFocus
              placeholder="ABC123"
            />
          </Campo>
          <Campo etiqueta="Tipo">
            <Selector
              valor={datos.tipo}
              onChange={(v) => setDatos((p) => ({ ...p, tipo: v }))}
              opciones={TIPOS_VEHICULO}
              vacio={null}
            />
          </Campo>
          <Campo etiqueta="Capacidad (kg)">
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={datos.capacidad_kg}
              onChange={cambiar("capacidad_kg")}
              required
              placeholder="8000"
            />
          </Campo>
          <Campo etiqueta="Volumen (m³)">
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={datos.capacidad_m3}
              onChange={cambiar("capacidad_m3")}
              required
              placeholder="30"
            />
          </Campo>
          <Campo etiqueta="Año">
            <input
              type="number"
              min="1990"
              max="2100"
              value={datos.anio}
              onChange={cambiar("anio")}
              required
            />
          </Campo>
          <Campo etiqueta="Vencimiento del seguro" ayuda="Si está vencido, deja de ser asignable">
            <input
              type="date"
              value={datos.vencimiento_seguro}
              onChange={cambiar("vencimiento_seguro")}
              required
            />
          </Campo>
          <Campo etiqueta="Zona de operación">
            <input value={datos.zona_operacion} onChange={cambiar("zona_operacion")} required />
          </Campo>
          <div className="campo">
            <span className="etiqueta-campo">Capacidades especiales</span>
            <div className="casillas">
              <label>
                <input type="checkbox" checked={datos.refrigerado} onChange={cambiar("refrigerado")} />
                Refrigerado
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={datos.certificado_hazmat}
                  onChange={cambiar("certificado_hazmat")}
                />
                Hazmat
              </label>
            </div>
          </div>
        </div>
        <footer className="acciones-formulario">
          <button type="button" className="boton fantasma" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" className="boton" disabled={enviando}>
            {enviando ? "Creando…" : "Crear vehículo"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------------- cambio de estado */

function CambiarEstado({ vehiculo, onCerrar, onCambiado }) {
  const [estado, setEstado] = useState(
    ESTADOS_VEHICULO.find((e) => e !== vehiculo.estado) || "disponible"
  );
  const [motivo, setMotivo] = useState("");
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);

  const enviar = async (evento) => {
    evento.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      const actualizado = await fleet.cambiarEstado(vehiculo.id, estado, motivo);
      onCambiado(actualizado);
    } catch (fallo) {
      setError(fallo);
      setEnviando(false);
    }
  };

  return (
    <Modal titulo={`Cambiar estado — ${vehiculo.placa}`} onCerrar={onCerrar} ancho="480px">
      <form onSubmit={enviar}>
        <Error_ error={error} />
        <p className="descripcion">
          Estado actual: <Etiqueta valor={vehiculo.estado} />. El cambio escribe la fila de{" "}
          <code className="mono">outbox_eventos</code> en la misma transacción y publica{" "}
          <code className="mono">vehicle.status_changed</code> al bus.
        </p>
        <Campo etiqueta="Nuevo estado">
          <Selector
            valor={estado}
            onChange={setEstado}
            opciones={ESTADOS_VEHICULO.filter((e) => e !== vehiculo.estado)}
            vacio={null}
          />
        </Campo>
        <Campo etiqueta="Motivo" ayuda="Mínimo 3 caracteres; queda en el payload del evento">
          <input
            value={motivo}
            onChange={(e) => setMotivo(e.target.value)}
            minLength={3}
            maxLength={200}
            required
            autoFocus
            placeholder="revisión de frenos programada"
          />
        </Campo>
        <footer className="acciones-formulario">
          <button type="button" className="boton fantasma" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" className="boton" disabled={enviando}>
            {enviando ? "Aplicando…" : "Cambiar estado"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

/* ------------------------------------------- ficha combinada (REST síncrono) */

function FichaVehiculo({ vehiculo, onCerrar }) {
  const { datos, cargando, error, recargar } = useCargar(
    () => mantenimiento.ficha(vehiculo.id),
    [vehiculo.id]
  );

  return (
    <Modal titulo={`Ficha combinada — ${vehiculo.placa}`} onCerrar={onCerrar} ancho="760px">
      <p className="descripcion">
        La pide <strong>Maintenance</strong>, que no tiene tabla de vehículos: para responder hace un{" "}
        <code className="mono">GET /api/v1/vehiculos/{"{id}"}</code> contra Fleet por REST síncrono y
        lo une con su propio historial. Es el único punto del sistema donde un servicio no puede
        continuar sin la respuesta del otro.
      </p>

      {cargando && <Cargando texto="Consultando a Maintenance…" />}
      <Error_ error={error} onReintentar={recargar} />

      {datos && (
        <>
          {datos.fuente === "fleet" ? (
            <Aviso tipo="ok">
              Fleet respondió: los datos del vehículo vienen del servicio dueño del dato.
            </Aviso>
          ) : (
            <Aviso tipo="alerta">
              <strong>Plan B en acción.</strong> Fleet no respondió ({datos.detalle_consulta}), así
              que Maintenance devuelve solo la parte que es suya en vez de fallar con un 500.
            </Aviso>
          )}

          {datos.vehiculo && (
            <div className="rejilla datos">
              <div>
                <span className="etiqueta-campo">Tipo</span>
                <span>{String(datos.vehiculo.tipo).replace(/_/g, " ")}</span>
              </div>
              <div>
                <span className="etiqueta-campo">Estado</span>
                <Etiqueta valor={datos.vehiculo.estado} />
              </div>
              <div>
                <span className="etiqueta-campo">Capacidad</span>
                <span>
                  {numero(datos.vehiculo.capacidad_kg)} kg · {numero(datos.vehiculo.capacidad_m3, 1)}{" "}
                  m³
                </span>
              </div>
              <div>
                <span className="etiqueta-campo">Zona</span>
                <span>{datos.vehiculo.zona_operacion}</span>
              </div>
            </div>
          )}

          <h4 className="subtitulo">Historial de mantenimiento ({datos.programa.length})</h4>
          <Tabla
            columnas={["Fecha prevista", "Estado", "Origen", "Prioridad", "Motivo"]}
            vacio="Este vehículo no tiene programas ni alertas registradas."
          >
            {datos.programa.length > 0 &&
              datos.programa.map((p) => (
                <tr key={p.id}>
                  <td>{fecha(p.fecha_prevista)}</td>
                  <td>
                    <Etiqueta valor={p.estado} />
                  </td>
                  <td>{p.origen}</td>
                  <td>P{p.prioridad}</td>
                  <td className="tenue">{p.motivo || "—"}</td>
                </tr>
              ))}
          </Tabla>
        </>
      )}
    </Modal>
  );
}

/* ------------------------------------------------------------------ tabla */

function Seguro({ iso }) {
  const dias = diasHasta(iso);
  if (dias < 0) return <span className="alerta-texto">vencido</span>;
  if (dias < 30) return <span className="alerta-texto">vence en {dias} d</span>;
  return <span className="tenue">{fecha(iso)}</span>;
}

export default function Flota() {
  const [filtros, setFiltros] = useState({ estado: "", tipo: "", zona: "", placa: "" });
  const [soloAsignables, setSoloAsignables] = useState(false);
  const [pagina, setPagina] = useState(0);
  const [creando, setCreando] = useState(false);
  const [cambiando, setCambiando] = useState(null);
  const [ficha, setFicha] = useState(null);
  const [nota, setNota] = useState(null);

  const clave = JSON.stringify({ filtros, soloAsignables, pagina });
  const { datos, cargando, error, recargar } = useCargar(async () => {
    if (soloAsignables) {
      // /disponibles no pagina: devuelve la lista completa de asignables.
      const items = await fleet.disponibles({
        tipo: filtros.tipo,
        zona: filtros.zona,
      });
      return { items, total: items.length, paginado: false };
    }
    const pagina_ = await fleet.listar({
      ...filtros,
      limite: POR_PAGINA,
      desplazamiento: pagina * POR_PAGINA,
    });
    return { ...pagina_, paginado: true };
  }, [clave]);

  const cambiarFiltro = (clave_) => (valor) => {
    setPagina(0);
    setFiltros((previo) => ({ ...previo, [clave_]: valor }));
  };

  const items = datos?.items || [];
  const total = datos?.total || 0;
  const ultimaPagina = Math.max(0, Math.ceil(total / POR_PAGINA) - 1);

  return (
    <>
      <Panel
        titulo="Catálogo de flota"
        descripcion="Vehículos y conductores son el maestro que el resto del sistema consulta antes de asignar una carga."
        acciones={
          <>
            <button className="boton fantasma" onClick={recargar} disabled={cargando}>
              Actualizar
            </button>
            <button className="boton" onClick={() => setCreando(true)}>
              Nuevo vehículo
            </button>
          </>
        }
      >
        <Aviso tipo="ok" onCerrar={() => setNota(null)}>
          {nota}
        </Aviso>

        <div className="filtros">
          <Campo etiqueta="Placa">
            <input
              value={filtros.placa}
              onChange={(e) => cambiarFiltro("placa")(e.target.value)}
              placeholder="buscar…"
              disabled={soloAsignables}
            />
          </Campo>
          <Campo etiqueta="Estado">
            <Selector
              valor={filtros.estado}
              onChange={cambiarFiltro("estado")}
              opciones={ESTADOS_VEHICULO}
              disabled={soloAsignables}
            />
          </Campo>
          <Campo etiqueta="Tipo">
            <Selector valor={filtros.tipo} onChange={cambiarFiltro("tipo")} opciones={TIPOS_VEHICULO} />
          </Campo>
          <Campo etiqueta="Zona">
            <input
              value={filtros.zona}
              onChange={(e) => cambiarFiltro("zona")(e.target.value)}
              placeholder="montería"
            />
          </Campo>
          <label className="conmutador" title="Usa GET /vehiculos/disponibles, la consulta de Routing">
            <input
              type="checkbox"
              checked={soloAsignables}
              onChange={(e) => {
                setSoloAsignables(e.target.checked);
                setPagina(0);
              }}
            />
            Solo asignables
          </label>
        </div>

        {soloAsignables && (
          <Aviso tipo="info">
            Consultando <code className="mono">/api/v1/vehiculos/disponibles</code> — la misma llamada
            que hace Routing: estado <em>disponible</em> y seguro vigente. Los demás filtros no aplican.
          </Aviso>
        )}

        <Error_ error={error} onReintentar={recargar} />
        {cargando && <Cargando />}

        {!cargando && !error && (
          <>
            <Tabla
              columnas={[
                "Placa",
                "Tipo",
                "Capacidad",
                "Año",
                "Zona",
                "Seguro",
                "Especiales",
                "Estado",
                "ID",
                "",
              ]}
              vacio={
                soloAsignables
                  ? "Ningún vehículo cumple los requisitos de asignación ahora mismo."
                  : "No hay vehículos con estos filtros. Crea uno o ejecuta scripts/seed.py."
              }
            >
              {items.length > 0 &&
                items.map((v) => (
                  <tr key={v.id}>
                    <td className="mono fuerte">{v.placa}</td>
                    <td>{v.tipo.replace(/_/g, " ")}</td>
                    <td>
                      {numero(v.capacidad_kg)} kg
                      <span className="tenue"> · {numero(v.capacidad_m3, 1)} m³</span>
                    </td>
                    <td>{v.anio}</td>
                    <td>{v.zona_operacion}</td>
                    <td>
                      <Seguro iso={v.vencimiento_seguro} />
                    </td>
                    <td>
                      {v.refrigerado && <span className="etiqueta azul">frío</span>}
                      {v.certificado_hazmat && <span className="etiqueta morado">hazmat</span>}
                      {!v.refrigerado && !v.certificado_hazmat && <span className="tenue">—</span>}
                    </td>
                    <td>
                      <Etiqueta valor={v.estado} />
                    </td>
                    <td>
                      <Id valor={v.id} />
                    </td>
                    <td className="acciones-fila">
                      <button className="boton menor" onClick={() => setCambiando(v)}>
                        Estado
                      </button>
                      <button className="boton menor fantasma" onClick={() => setFicha(v)}>
                        Ficha
                      </button>
                    </td>
                  </tr>
                ))}
            </Tabla>

            <footer className="pie-tabla">
              <span className="tenue">
                {total} {total === 1 ? "vehículo" : "vehículos"}
                {datos?.paginado && total > POR_PAGINA && ` · página ${pagina + 1} de ${ultimaPagina + 1}`}
              </span>
              {datos?.paginado && total > POR_PAGINA && (
                <div className="paginacion">
                  <button
                    className="boton menor fantasma"
                    onClick={() => setPagina((p) => p - 1)}
                    disabled={pagina === 0}
                  >
                    ← Anterior
                  </button>
                  <button
                    className="boton menor fantasma"
                    onClick={() => setPagina((p) => p + 1)}
                    disabled={pagina >= ultimaPagina}
                  >
                    Siguiente →
                  </button>
                </div>
              )}
            </footer>
          </>
        )}
      </Panel>

      {creando && (
        <FormularioVehiculo
          onCerrar={() => setCreando(false)}
          onCreado={(v) => {
            setCreando(false);
            setNota(`Vehículo ${v.placa} creado.`);
            recargar();
          }}
        />
      )}

      {cambiando && (
        <CambiarEstado
          vehiculo={cambiando}
          onCerrar={() => setCambiando(null)}
          onCambiado={(v) => {
            setCambiando(null);
            setNota(
              `${v.placa} pasó a ${v.estado.replace(/_/g, " ")} · vehicle.status_changed encolado en el outbox.`
            );
            recargar();
          }}
        />
      )}

      {ficha && <FichaVehiculo vehiculo={ficha} onCerrar={() => setFicha(null)} />}
    </>
  );
}
