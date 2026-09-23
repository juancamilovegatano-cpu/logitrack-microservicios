/**
 * Pestaña Comunicación síncrona — sección 05 del documento.
 *
 * Fleet y Maintenance se hablan de dos formas y esta vista muestra la que no se
 * ve en las otras pestañas: la llamada REST que Maintenance no puede evitar.
 * El endpoint /dependencias expone el estado real del circuit breaker, así que
 * aquí se puede demostrar en vivo el paso cerrado -> abierto -> semiabierto.
 */

import { useEffect, useRef, useState } from "react";

import { DIRECCIONES, mantenimiento } from "../api.js";
import { Aviso, Cargando, Error_, Panel, Tabla, numero, useCargar } from "../ui.jsx";

const ESTADOS = [
  {
    id: "cerrado",
    titulo: "1 · Cerrado",
    detalle: "Todo pasa con normalidad. Se cuentan los fallos.",
  },
  {
    id: "abierto",
    titulo: "2 · Abierto",
    detalle: "Se rechaza al instante sin llamar. Se usa el plan B.",
  },
  {
    id: "semiabierto",
    titulo: "3 · Semiabierto",
    detalle: "Deja pasar una sola petición de prueba.",
  },
];

/** UUID fijo e inexistente: solo sirve para que el cliente REST intente salir. */
const UUID_SONDA = "00000000-0000-4000-8000-000000000000";

export default function Resiliencia() {
  const [refresco, setRefresco] = useState(0);
  const [forzando, setForzando] = useState(null);
  const [nota, setNota] = useState(null);
  const montado = useRef(true);

  const { datos, cargando, error, recargar } = useCargar(
    () => mantenimiento.dependencias(),
    [refresco]
  );

  // El estado del circuito cambia solo (la cuenta atrás corre en el servicio),
  // así que se sondea cada 2 s mientras la pestaña está abierta.
  useEffect(() => {
    montado.current = true;
    const id = setInterval(() => montado.current && setRefresco((n) => n + 1), 2000);
    return () => {
      montado.current = false;
      clearInterval(id);
    };
  }, []);

  /**
   * Provoca fallos reales contra Fleet para abrir el circuito.
   * Solo tiene efecto si Fleet está caído: con Fleet en pie responde 404, que
   * el cliente trata como respuesta válida y NO cuenta como fallo.
   */
  const forzarFallos = async () => {
    setNota(null);
    for (let intento = 1; intento <= 5; intento += 1) {
      setForzando(intento);
      try {
        await mantenimiento.ficha(UUID_SONDA);
      } catch {
        /* se espera que falle: de eso se trata */
      }
      if (!montado.current) return;
    }
    setForzando(null);
    setNota(
      "Cinco intentos lanzados. Si Fleet está caído, el circuito ya debería estar abierto abajo."
    );
  };

  const cb = datos?.circuit_breaker;
  const politica = datos?.politica;
  const fleetVivo = datos?.fleet?.alcanzable;

  return (
    <Panel
      titulo="Comunicación síncrona y circuit breaker"
      descripcion="Maintenance es el único cliente REST de Fleet en este par. Esta vista muestra el estado real de esa dependencia."
    >
      <Aviso tipo="ok" onCerrar={() => setNota(null)}>
        {nota}
      </Aviso>

      <Error_ error={error} onReintentar={recargar} />
      {cargando && !datos && <Cargando texto="Consultando /dependencias…" />}

      {datos && (
        <>
          <div className="rejilla datos">
            <div>
              <span className="etiqueta-campo">Servicio</span>
              <span className="mono">{datos.servicio}</span>
            </div>
            <div>
              <span className="etiqueta-campo">Llama a</span>
              <span className="mono">{datos.fleet_base_url}</span>
            </div>
            <div>
              <span className="etiqueta-campo">Fleet alcanzable</span>
              <span className={fleetVivo ? "ok-texto" : "alerta-texto"}>
                {fleetVivo ? `sí (HTTP ${datos.fleet.http})` : `no — ${datos.fleet.error || "sin respuesta"}`}
              </span>
            </div>
            <div>
              <span className="etiqueta-campo">Fallos en ventana</span>
              <span>
                {cb.fallos_en_ventana} / {cb.umbral_fallos}
                <span className="tenue"> en {numero(cb.ventana_segundos)} s</span>
              </span>
            </div>
          </div>

          <h4 className="subtitulo">Estado del circuito</h4>
          <div className="circuito">
            {ESTADOS.map((e) => (
              <div key={e.id} className={`estado-circuito ${cb.estado === e.id ? "activo" : ""}`}>
                <strong>{e.titulo}</strong>
                <span>{e.detalle}</span>
                {cb.estado === e.id && e.id === "abierto" && (
                  <span className="cuenta">
                    semiabierto en {numero(cb.segundos_para_semiabierto, 1)} s
                  </span>
                )}
                {cb.estado === e.id && <span className="marca">estado actual</span>}
              </div>
            ))}
          </div>

          <div className="filtros">
            <button className="boton" onClick={forzarFallos} disabled={forzando !== null}>
              {forzando ? `Intento ${forzando} de 5…` : "Provocar 5 fallos"}
            </button>
            <span className="tenue">
              Para verlo abrir:{" "}
              <code className="mono">docker compose stop fleet-service</code> y pulsa el botón. Cada
              intento agota {numero(politica.timeout_segundos)} s de timeout más los reintentos, así
              que tarda cerca de un minuto.
            </span>
          </div>

          {fleetVivo && (
            <Aviso tipo="info">
              Fleet está en pie: sus 404 son respuestas válidas y <strong>no</strong> cuentan como
              fallo, así que el circuito no se abrirá. Es el comportamiento correcto — un servicio que
              contesta &quot;no existe&quot; está sano.
            </Aviso>
          )}

          <h4 className="subtitulo">Política aplicada</h4>
          <Tabla columnas={["Parámetro", "Valor", "Qué hace"]}>
            <tr>
              <td>Timeout</td>
              <td className="mono">{numero(politica.timeout_segundos)} s</td>
              <td className="tenue">
                Sin timeout explícito, una conexión colgada bloquea un hilo y agota el pool.
              </td>
            </tr>
            <tr>
              <td>Reintentos</td>
              <td className="mono">{politica.max_intentos} intentos</td>
              <td className="tenue">Solo sobre GET, que es idempotente.</td>
            </tr>
            <tr>
              <td>Retroceso</td>
              <td className="mono">
                {politica.backoff_segundos.map((s) => `${numero(s)} s`).join(" · ")}
              </td>
              <td className="tenue">
                Exponencial, más hasta {numero(politica.jitter_maximo_segundos, 1)} s de jitter para
                que las réplicas no reintenten a la vez.
              </td>
            </tr>
            <tr>
              <td>Umbral del circuito</td>
              <td className="mono">
                {politica.breaker_umbral_fallos} fallos / {numero(politica.breaker_ventana_segundos)} s
              </td>
              <td className="tenue">Ventana deslizante: los fallos viejos no cuentan.</td>
            </tr>
            <tr>
              <td>Espera en abierto</td>
              <td className="mono">{numero(politica.breaker_espera_abierto_segundos)} s</td>
              <td className="tenue">Después deja pasar una única petición de prueba.</td>
            </tr>
          </Tabla>

          <p className="descripcion">
            El plan B está en el consumidor de telemetría: si Fleet no responde, la alerta se abre
            igual con los datos que trae el evento, solo que sin placa ni tipo. Una alerta sin placa
            es mejor que un motor fundido.
          </p>

          <p className="descripcion tenue">
            Panel apuntando a <code className="mono">{DIRECCIONES.fleet}</code> y{" "}
            <code className="mono">{DIRECCIONES.mantenimiento}</code>.
          </p>
        </>
      )}
    </Panel>
  );
}
