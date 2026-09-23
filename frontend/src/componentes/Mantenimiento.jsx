/**
 * Pestaña Mantenimiento — Maintenance Service (ficha 3.6).
 *
 * Tres vistas sobre el mismo servicio: las alertas que abrió el consumidor de
 * telemetry.aggregated, el calendario preventivo y las reglas de umbral que
 * gobiernan ambas cosas. Registrar una intervención cierra el programa, publica
 * maintenance.completed y abre el siguiente ciclo preventivo — todo en una
 * transacción del lado del servicio.
 */

import { useState } from "react";

import { METRICAS, TIPOS_VEHICULO, mantenimiento } from "../api.js";
import {
  Aviso,
  Campo,
  Cargando,
  Error_,
  Etiqueta,
  Id,
  Modal,
  Panel,
  Prioridad,
  Selector,
  Tabla,
  diasHasta,
  fecha,
  fechaHora,
  numero,
  useCargar,
} from "../ui.jsx";

const VISTAS = [
  { id: "alertas", nombre: "Alertas" },
  { id: "proximos", nombre: "Calendario" },
  { id: "reglas", nombre: "Reglas de umbral" },
];

const ABIERTOS = ["pendiente", "programado", "en_taller"];

/** Valor para <input type="datetime-local"> en hora local, sin librerías. */
function ahoraLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

/* ------------------------------------------------------ nueva regla */

function FormularioRegla({ onCerrar, onCreada }) {
  const [datos, setDatos] = useState({
    nombre: "",
    tipo_vehiculo: "",
    metrica: "temperatura_motor_c",
    umbral: "",
    comparador: "mayor",
    prioridad: 3,
  });
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);

  const poner = (clave) => (valor) => setDatos((previo) => ({ ...previo, [clave]: valor }));

  const enviar = async (evento) => {
    evento.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      const creada = await mantenimiento.crearRegla({
        ...datos,
        // cadena vacía = "aplica a todos los tipos"; el backend espera null
        tipo_vehiculo: datos.tipo_vehiculo || null,
        umbral: Number(datos.umbral),
        prioridad: Number(datos.prioridad),
      });
      onCreada(creada);
    } catch (fallo) {
      setError(fallo);
      setEnviando(false);
    }
  };

  return (
    <Modal titulo="Nueva regla de umbral" onCerrar={onCerrar} ancho="620px">
      <form onSubmit={enviar}>
        <Error_ error={error} />
        <p className="descripcion">
          Cada lectura de <code className="mono">telemetry.aggregated</code> se compara contra las
          reglas activas. Si cruza el umbral y no hay ya una alerta abierta por la misma regla, se
          crea el programa y se publica <code className="mono">maintenance.alert</code>.
        </p>

        <Campo etiqueta="Nombre">
          <input
            value={datos.nombre}
            onChange={(e) => poner("nombre")(e.target.value)}
            minLength={3}
            maxLength={120}
            required
            autoFocus
            placeholder="Sobrecalentamiento de motor"
          />
        </Campo>

        <div className="rejilla dos">
          <Campo etiqueta="Métrica">
            <Selector
              valor={datos.metrica}
              onChange={poner("metrica")}
              opciones={METRICAS}
              vacio={null}
            />
          </Campo>
          <Campo etiqueta="Tipo de vehículo" ayuda="Vacío = aplica a todos">
            <Selector
              valor={datos.tipo_vehiculo}
              onChange={poner("tipo_vehiculo")}
              opciones={TIPOS_VEHICULO}
              vacio="Todos los tipos"
            />
          </Campo>
          <Campo etiqueta="Comparador">
            <Selector
              valor={datos.comparador}
              onChange={poner("comparador")}
              opciones={[
                { valor: "mayor", texto: "dispara si el valor es MAYOR que el umbral" },
                { valor: "menor", texto: "dispara si el valor es MENOR que el umbral" },
              ]}
              vacio={null}
            />
          </Campo>
          <Campo etiqueta="Umbral">
            <input
              type="number"
              step="0.01"
              value={datos.umbral}
              onChange={(e) => poner("umbral")(e.target.value)}
              required
              placeholder="105"
            />
          </Campo>
          <Campo etiqueta="Prioridad" ayuda="1 = taller hoy mismo · 5 = en 15 días">
            <Selector
              valor={String(datos.prioridad)}
              onChange={poner("prioridad")}
              opciones={[
                { valor: "1", texto: "P1 — hoy mismo" },
                { valor: "2", texto: "P2 — mañana" },
                { valor: "3", texto: "P3 — en 3 días" },
                { valor: "4", texto: "P4 — en 7 días" },
                { valor: "5", texto: "P5 — en 15 días" },
              ]}
              vacio={null}
            />
          </Campo>
        </div>

        <footer className="acciones-formulario">
          <button type="button" className="boton fantasma" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" className="boton" disabled={enviando}>
            {enviando ? "Creando…" : "Crear regla"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

/* ------------------------------------------------ registrar intervención */

function FormularioIntervencion({ programa, onCerrar, onRegistrada }) {
  const [datos, setDatos] = useState({
    realizado_en: ahoraLocal(),
    costo: "",
    taller: "",
    km_al_servicio: programa.km_previsto ?? "",
    notas: "",
  });
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);

  const cambiar = (clave) => (evento) =>
    setDatos((previo) => ({ ...previo, [clave]: evento.target.value }));

  const enviar = async (evento) => {
    evento.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      const creada = await mantenimiento.registrarIntervencion({
        programa_id: programa.id,
        // datetime-local no lleva zona: se convierte a ISO con la del navegador
        realizado_en: new Date(datos.realizado_en).toISOString(),
        costo: Number(datos.costo),
        taller: datos.taller,
        km_al_servicio: Number(datos.km_al_servicio),
        notas: datos.notas || null,
      });
      onRegistrada(creada);
    } catch (fallo) {
      setError(fallo);
      setEnviando(false);
    }
  };

  return (
    <Modal titulo="Registrar intervención" onCerrar={onCerrar} ancho="620px">
      <form onSubmit={enviar}>
        <Error_ error={error} />
        <Aviso tipo="info">
          Al guardar, el servicio cierra este programa, publica{" "}
          <code className="mono">maintenance.completed</code> — que Fleet consume para devolver el
          vehículo a <em>disponible</em> — y abre el siguiente ciclo preventivo a 180 días o 15 000 km.
        </Aviso>

        <div className="rejilla datos compacta">
          <div>
            <span className="etiqueta-campo">Programa</span>
            <Id valor={programa.id} />
          </div>
          <div>
            <span className="etiqueta-campo">Vehículo</span>
            <Id valor={programa.vehiculo_id} />
          </div>
          <div>
            <span className="etiqueta-campo">Motivo</span>
            <span className="tenue">{programa.motivo || "—"}</span>
          </div>
        </div>

        <div className="rejilla dos">
          <Campo etiqueta="Realizado el">
            <input
              type="datetime-local"
              value={datos.realizado_en}
              onChange={cambiar("realizado_en")}
              required
            />
          </Campo>
          <Campo etiqueta="Taller">
            <input
              value={datos.taller}
              onChange={cambiar("taller")}
              minLength={2}
              maxLength={120}
              required
              placeholder="Taller Central Montería"
            />
          </Campo>
          <Campo etiqueta="Costo (COP)">
            <input
              type="number"
              step="0.01"
              min="0"
              value={datos.costo}
              onChange={cambiar("costo")}
              required
              placeholder="450000"
            />
          </Campo>
          <Campo etiqueta="Kilometraje al servicio" ayuda="Base del próximo ciclo preventivo">
            <input
              type="number"
              min="0"
              value={datos.km_al_servicio}
              onChange={cambiar("km_al_servicio")}
              required
              placeholder="84000"
            />
          </Campo>
        </div>

        <Campo etiqueta="Notas">
          <textarea rows={3} value={datos.notas} onChange={cambiar("notas")} />
        </Campo>

        <footer className="acciones-formulario">
          <button type="button" className="boton fantasma" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" className="boton" disabled={enviando}>
            {enviando ? "Registrando…" : "Registrar y cerrar programa"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

/* -------------------------------------------------------------- vistas */

function FilaPrograma({ programa, onIntervenir }) {
  const dias = diasHasta(programa.fecha_prevista);
  const abierto = ABIERTOS.includes(programa.estado);
  return (
    <tr>
      <td>
        <Prioridad valor={programa.prioridad} />
      </td>
      <td>
        <Id valor={programa.vehiculo_id} />
      </td>
      <td>
        {fecha(programa.fecha_prevista)}
        {abierto && (
          <span className={dias < 0 ? "alerta-texto" : "tenue"}>
            {dias < 0 ? ` · vencida hace ${-dias} d` : dias === 0 ? " · hoy" : ` · en ${dias} d`}
          </span>
        )}
      </td>
      <td>
        <Etiqueta valor={programa.estado} />
      </td>
      <td>{programa.origen}</td>
      <td>{programa.km_previsto ? `${numero(programa.km_previsto)} km` : <span className="tenue">—</span>}</td>
      <td className="tenue motivo">{programa.motivo || "—"}</td>
      <td className="tenue">{fechaHora(programa.creado_en)}</td>
      <td className="acciones-fila">
        {abierto ? (
          <button className="boton menor" onClick={() => onIntervenir(programa)}>
            Intervenir
          </button>
        ) : (
          <span className="tenue">cerrado</span>
        )}
      </td>
    </tr>
  );
}

const COLUMNAS = [
  "Prioridad",
  "Vehículo",
  "Fecha prevista",
  "Estado",
  "Origen",
  "Km previsto",
  "Motivo",
  "Creado",
  "",
];

function Alertas({ onIntervenir, refresco }) {
  const [estado, setEstado] = useState("abierta");
  const { datos, cargando, error, recargar } = useCargar(
    () => mantenimiento.alertas(estado),
    [estado, refresco]
  );
  const items = datos || [];

  return (
    <>
      <div className="filtros">
        <Campo etiqueta="Estado de la alerta">
          <Selector
            valor={estado}
            onChange={setEstado}
            opciones={[
              { valor: "abierta", texto: "Abiertas (pendiente · programado · en taller)" },
              { valor: "cerrada", texto: "Cerradas (completado · cancelado)" },
            ]}
            vacio={null}
          />
        </Campo>
        <button className="boton fantasma" onClick={recargar} disabled={cargando}>
          Actualizar
        </button>
      </div>

      <Aviso tipo="info">
        Estas filas no las creó nadie a mano: las abrió el consumidor de{" "}
        <code className="mono">telemetry.aggregated</code> al cruzar un umbral. Para verlas aparecer,
        ejecuta <code className="mono">python scripts/demo_e2e.py</code>.
      </Aviso>

      <Error_ error={error} onReintentar={recargar} />
      {cargando && <Cargando />}
      {!cargando && !error && (
        <Tabla
          columnas={COLUMNAS}
          vacio={
            estado === "abierta"
              ? "Ninguna alerta abierta. Toda la flota dentro de umbrales."
              : "Todavía no se ha cerrado ninguna alerta."
          }
        >
          {items.length > 0 &&
            items.map((p) => <FilaPrograma key={p.id} programa={p} onIntervenir={onIntervenir} />)}
        </Tabla>
      )}
    </>
  );
}

function Proximos({ onIntervenir, refresco }) {
  const [dias, setDias] = useState(90);
  const { datos, cargando, error, recargar } = useCargar(
    () => mantenimiento.proximos(dias),
    [dias, refresco]
  );
  const items = datos || [];

  return (
    <>
      <div className="filtros">
        <Campo etiqueta="Ventana (días)" ayuda="Entre 1 y 365">
          <input
            type="number"
            min={1}
            max={365}
            value={dias}
            onChange={(e) => setDias(Number(e.target.value) || 1)}
          />
        </Campo>
        <button className="boton fantasma" onClick={recargar} disabled={cargando}>
          Actualizar
        </button>
      </div>

      <Error_ error={error} onReintentar={recargar} />
      {cargando && <Cargando />}
      {!cargando && !error && (
        <Tabla
          columnas={COLUMNAS}
          vacio={`Nada programado en los próximos ${dias} días (pendientes y programados).`}
        >
          {items.length > 0 &&
            items.map((p) => <FilaPrograma key={p.id} programa={p} onIntervenir={onIntervenir} />)}
        </Tabla>
      )}
    </>
  );
}

function Reglas() {
  const [creando, setCreando] = useState(false);
  const { datos, cargando, error, recargar } = useCargar(() => mantenimiento.reglas(), []);
  const items = datos || [];

  return (
    <>
      <div className="filtros">
        <button className="boton" onClick={() => setCreando(true)}>
          Nueva regla
        </button>
        <button className="boton fantasma" onClick={recargar} disabled={cargando}>
          Actualizar
        </button>
      </div>

      <Error_ error={error} onReintentar={recargar} />
      {cargando && <Cargando />}
      {!cargando && !error && (
        <Tabla
          columnas={["Nombre", "Métrica", "Condición", "Aplica a", "Prioridad", "Activa", "ID"]}
          vacio="No hay reglas cargadas: sin ellas ninguna telemetría genera alertas."
        >
          {items.length > 0 &&
            items.map((r) => (
              <tr key={r.id}>
                <td className="fuerte">{r.nombre}</td>
                <td className="mono">{r.metrica}</td>
                <td>
                  {r.comparador === "mayor" ? "＞" : "＜"} {numero(r.umbral, 2)}
                </td>
                <td>
                  {r.tipo_vehiculo ? (
                    r.tipo_vehiculo.replace(/_/g, " ")
                  ) : (
                    <span className="tenue">todos los tipos</span>
                  )}
                </td>
                <td>
                  <Prioridad valor={r.prioridad} />
                </td>
                <td>
                  {r.activa ? <Etiqueta valor="activa" tono="verde" /> : <Etiqueta valor="inactiva" />}
                </td>
                <td>
                  <Id valor={r.id} />
                </td>
              </tr>
            ))}
        </Tabla>
      )}

      {creando && (
        <FormularioRegla
          onCerrar={() => setCreando(false)}
          onCreada={() => {
            setCreando(false);
            recargar();
          }}
        />
      )}
    </>
  );
}

/* --------------------------------------------------------------- pestaña */

export default function Mantenimiento() {
  const [vista, setVista] = useState("alertas");
  const [interviniendo, setInterviniendo] = useState(null);
  const [nota, setNota] = useState(null);
  const [refresco, setRefresco] = useState(0);

  return (
    <>
      <Panel
        titulo="Mantenimiento predictivo"
        descripcion="Reglas de umbral, alertas abiertas por telemetría y calendario de taller."
      >
        <Aviso tipo="ok" onCerrar={() => setNota(null)}>
          {nota}
        </Aviso>

        <nav className="subtabs">
          {VISTAS.map((v) => (
            <button
              key={v.id}
              className={vista === v.id ? "activa" : ""}
              onClick={() => setVista(v.id)}
            >
              {v.nombre}
            </button>
          ))}
        </nav>

        {vista === "alertas" && <Alertas onIntervenir={setInterviniendo} refresco={refresco} />}
        {vista === "proximos" && <Proximos onIntervenir={setInterviniendo} refresco={refresco} />}
        {vista === "reglas" && <Reglas />}
      </Panel>

      {interviniendo && (
        <FormularioIntervencion
          programa={interviniendo}
          onCerrar={() => setInterviniendo(null)}
          onRegistrada={(i) => {
            setInterviniendo(null);
            setNota(
              `Intervención registrada en ${i.taller} · maintenance.completed encolado y ciclo preventivo abierto.`
            );
            setRefresco((n) => n + 1);
          }}
        />
      )}
    </>
  );
}
