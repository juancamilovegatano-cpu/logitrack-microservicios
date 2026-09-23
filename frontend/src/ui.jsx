/**
 * Primitivas de interfaz compartidas por las cuatro pestañas.
 * Sin librerías: todo es HTML y las clases de estilos.css.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ErrorApi, ErrorRed } from "./api.js";

/* --------------------------------------------------------------- carga */

/**
 * Ejecuta una petición y expone {datos, cargando, error, recargar}.
 * `claves` funciona como las dependencias de useEffect: cambia una y recarga.
 */
export function useCargar(peticion, claves = []) {
  const [estado, setEstado] = useState({ datos: null, cargando: true, error: null });
  const vigente = useRef(0);

  const recargar = useCallback(async () => {
    const turno = ++vigente.current;
    setEstado((previo) => ({ ...previo, cargando: true }));
    try {
      const datos = await peticion();
      // Una respuesta lenta de un filtro viejo no debe pisar a la actual.
      if (turno === vigente.current) setEstado({ datos, cargando: false, error: null });
    } catch (error) {
      if (turno === vigente.current) setEstado({ datos: null, cargando: false, error });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, claves);

  useEffect(() => {
    recargar();
  }, [recargar]);

  return { ...estado, recargar };
}

/* -------------------------------------------------------------- avisos */

export function mensajeDeError(error) {
  if (error instanceof ErrorRed) {
    return `${error.message}. ¿Están arriba los contenedores? docker compose ps`;
  }
  if (error instanceof ErrorApi) {
    return error.codigo === "validacion"
      ? `Datos inválidos — ${error.message}`
      : `${error.codigo} — ${error.message}`;
  }
  return error?.message || "Error desconocido";
}

export function Aviso({ tipo = "info", children, onCerrar }) {
  if (!children) return null;
  return (
    <div className={`aviso ${tipo}`} role={tipo === "error" ? "alert" : "status"}>
      <span>{children}</span>
      {onCerrar && (
        <button className="cerrar" onClick={onCerrar} aria-label="Cerrar aviso">
          ×
        </button>
      )}
    </div>
  );
}

export function Error_({ error, onReintentar }) {
  if (!error) return null;
  return (
    <div className="aviso error" role="alert">
      <span>{mensajeDeError(error)}</span>
      {onReintentar && (
        <button className="boton menor" onClick={onReintentar}>
          Reintentar
        </button>
      )}
    </div>
  );
}

export function Cargando({ texto = "Cargando…" }) {
  return (
    <div className="cargando">
      <span className="girando" aria-hidden="true" />
      {texto}
    </div>
  );
}

export function Vacio({ children }) {
  return <div className="vacio">{children}</div>;
}

/* ------------------------------------------------------------ etiquetas */

const TONO_ESTADO = {
  disponible: "verde",
  en_ruta: "azul",
  mantenimiento: "ambar",
  fuera_servicio: "rojo",
  pendiente: "ambar",
  programado: "azul",
  en_taller: "morado",
  completado: "verde",
  cancelado: "gris",
};

export function Etiqueta({ valor, tono }) {
  const clase = tono || TONO_ESTADO[valor] || "gris";
  return <span className={`etiqueta ${clase}`}>{String(valor).replace(/_/g, " ")}</span>;
}

export function Prioridad({ valor }) {
  // 1 es la más urgente (DIAS_POR_PRIORIDAD del backend: 1 = hoy mismo)
  const tono = valor <= 1 ? "rojo" : valor === 2 ? "ambar" : valor >= 5 ? "gris" : "azul";
  return <span className={`etiqueta ${tono}`}>P{valor}</span>;
}

/** UUID abreviado y copiable: los IDs son la moneda de cambio entre servicios. */
export function Id({ valor, etiqueta }) {
  const [copiado, setCopiado] = useState(false);
  if (!valor) return <span className="tenue">—</span>;

  const copiar = async () => {
    try {
      await navigator.clipboard.writeText(valor);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 1200);
    } catch {
      /* sin portapapeles (http sin permiso): no pasa nada */
    }
  };

  return (
    <button className="id" onClick={copiar} title={`Copiar ${valor}`}>
      <span className="mono">{etiqueta || String(valor).slice(0, 8)}</span>
      <span className="icono">{copiado ? "✓" : "⧉"}</span>
    </button>
  );
}

/* --------------------------------------------------------------- campos */

export function Campo({ etiqueta, ayuda, children }) {
  return (
    <label className="campo">
      <span className="etiqueta-campo">{etiqueta}</span>
      {children}
      {ayuda && <span className="ayuda">{ayuda}</span>}
    </label>
  );
}

export function Selector({ valor, onChange, opciones, vacio = "Todos", ...resto }) {
  return (
    <select value={valor} onChange={(e) => onChange(e.target.value)} {...resto}>
      {vacio !== null && <option value="">{vacio}</option>}
      {opciones.map((o) => {
        const v = typeof o === "string" ? o : o.valor;
        const t = typeof o === "string" ? o.replace(/_/g, " ") : o.texto;
        return (
          <option key={v} value={v}>
            {t}
          </option>
        );
      })}
    </select>
  );
}

/* --------------------------------------------------------------- panel */

export function Panel({ titulo, descripcion, acciones, children }) {
  return (
    <section className="panel">
      {(titulo || acciones) && (
        <header className="panel-cabecera">
          <div>
            {titulo && <h2>{titulo}</h2>}
            {descripcion && <p className="descripcion">{descripcion}</p>}
          </div>
          {acciones && <div className="acciones">{acciones}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Tabla({ columnas, children, vacio }) {
  return (
    <div className="tabla-scroll">
      <table>
        <thead>
          <tr>
            {columnas.map((c) => (
              <th key={c} scope="col">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {children || (
            <tr>
              <td colSpan={columnas.length} className="vacio-celda">
                {vacio}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

/* --------------------------------------------------------------- modal */

export function Modal({ titulo, onCerrar, children, ancho }) {
  useEffect(() => {
    const alTeclear = (e) => e.key === "Escape" && onCerrar();
    window.addEventListener("keydown", alTeclear);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", alTeclear);
      document.body.style.overflow = "";
    };
  }, [onCerrar]);

  return (
    <div className="fondo-modal" onMouseDown={(e) => e.target === e.currentTarget && onCerrar()}>
      <div className="modal" style={ancho ? { maxWidth: ancho } : undefined} role="dialog" aria-modal="true">
        <header className="modal-cabecera">
          <h3>{titulo}</h3>
          <button className="cerrar" onClick={onCerrar} aria-label="Cerrar">
            ×
          </button>
        </header>
        <div className="modal-cuerpo">{children}</div>
      </div>
    </div>
  );
}

/* --------------------------------------------------------------- fechas */

export function fecha(valor) {
  if (!valor) return "—";
  const d = new Date(valor);
  return d.toLocaleDateString("es-CO", { day: "2-digit", month: "short", year: "numeric" });
}

export function fechaHora(valor) {
  if (!valor) return "—";
  return new Date(valor).toLocaleString("es-CO", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function numero(valor, decimales = 0) {
  if (valor === null || valor === undefined) return "—";
  return Number(valor).toLocaleString("es-CO", {
    minimumFractionDigits: decimales,
    maximumFractionDigits: decimales,
  });
}

/** Días desde hoy hasta una fecha de calendario (negativo = vencida). */
export function diasHasta(iso) {
  const hoy = new Date();
  hoy.setHours(0, 0, 0, 0);
  const objetivo = new Date(`${iso}T00:00:00`);
  return Math.round((objetivo - hoy) / 86400000);
}
