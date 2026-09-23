/**
 * Único punto donde el panel habla con los microservicios.
 *
 * Nota de arquitectura: el panel llama a los DOS servicios directamente. En el
 * diseño completo de LogiTrack habría un API Gateway al frente (sección 06 del
 * documento) y el frontend solo conocería una dirección. Con dos servicios en
 * local se llaman directo para no montar un componente fuera del alcance.
 *
 * Todo lo que devuelve este módulo son datos ya parseados; los errores llegan
 * como ErrorApi, con el código de negocio separado del mensaje.
 */

const FLEET = import.meta.env.VITE_FLEET_URL || "http://localhost:8001";
const MAINT = import.meta.env.VITE_MAINT_URL || "http://localhost:8006";

export const DIRECCIONES = { fleet: FLEET, mantenimiento: MAINT };

/** Error de negocio de la API: {detail: {error, mensaje}} o 422 de Pydantic. */
export class ErrorApi extends Error {
  constructor(estado, codigo, mensaje) {
    super(mensaje);
    this.estado = estado;
    this.codigo = codigo;
  }
}

/** El servicio no respondió: caído, CORS mal puesto o red. No es un 4xx. */
export class ErrorRed extends Error {
  constructor(base) {
    super(`No hay respuesta de ${base}`);
    this.base = base;
  }
}

function describirValidacion(detalle) {
  // 422 de FastAPI: [{loc: ["body","capacidad_kg"], msg: "..."}]
  return detalle
    .map((d) => {
      const campo = (d.loc || []).filter((p) => p !== "body" && p !== "query").join(".");
      return campo ? `${campo}: ${d.msg}` : d.msg;
    })
    .join(" · ");
}

async function pedir(base, ruta, opciones = {}) {
  let respuesta;
  try {
    respuesta = await fetch(`${base}${ruta}`, {
      headers: { "Content-Type": "application/json" },
      ...opciones,
    });
  } catch {
    throw new ErrorRed(base);
  }

  if (respuesta.status === 204) return null;

  let cuerpo = null;
  try {
    cuerpo = await respuesta.json();
  } catch {
    cuerpo = null;
  }

  if (!respuesta.ok) {
    const detalle = cuerpo?.detail;
    if (Array.isArray(detalle)) {
      throw new ErrorApi(respuesta.status, "validacion", describirValidacion(detalle));
    }
    if (detalle && typeof detalle === "object") {
      // formato de error de negocio del documento: {error, mensaje}
      throw new ErrorApi(respuesta.status, detalle.error, detalle.mensaje ?? detalle.error);
    }
    throw new ErrorApi(respuesta.status, "http_" + respuesta.status, detalle || respuesta.statusText);
  }

  return cuerpo;
}

/** Construye ?a=1&b=2 saltándose vacíos, para no mandar filtros en blanco. */
function consulta(parametros = {}) {
  const q = new URLSearchParams();
  Object.entries(parametros).forEach(([clave, valor]) => {
    if (valor !== "" && valor !== null && valor !== undefined) q.append(clave, valor);
  });
  const cola = q.toString();
  return cola ? `?${cola}` : "";
}

// ------------------------------------------------------------------ Fleet

export const fleet = {
  salud: () => pedir(FLEET, "/ready"),

  /** Catálogo completo, en cualquier estado. Devuelve {total, limite, desplazamiento, items}. */
  listar: (filtros = {}) => pedir(FLEET, `/api/v1/vehiculos${consulta(filtros)}`),

  /** Solo los asignables: estado=disponible y seguro vigente. Lo que consulta Routing. */
  disponibles: (filtros = {}) =>
    pedir(FLEET, `/api/v1/vehiculos/disponibles${consulta(filtros)}`),

  obtener: (id) => pedir(FLEET, `/api/v1/vehiculos/${id}`),

  crearVehiculo: (datos) =>
    pedir(FLEET, "/api/v1/vehiculos", { method: "POST", body: JSON.stringify(datos) }),

  /** Publica vehicle.status_changed por el outbox, en la misma transacción. */
  cambiarEstado: (id, estado, motivo) =>
    pedir(FLEET, `/api/v1/vehiculos/${id}/estado`, {
      method: "PATCH",
      body: JSON.stringify({ estado, motivo }),
    }),

  listarConductores: (nombre) => pedir(FLEET, `/api/v1/conductores${consulta({ nombre })}`),

  crearConductor: (datos) =>
    pedir(FLEET, "/api/v1/conductores", { method: "POST", body: JSON.stringify(datos) }),

  disponibilidadConductor: (id) => pedir(FLEET, `/api/v1/conductores/${id}/disponibilidad`),
};

// ------------------------------------------------------------ Maintenance

export const mantenimiento = {
  salud: () => pedir(MAINT, "/ready"),

  reglas: () => pedir(MAINT, "/api/v1/mantenimiento/reglas"),

  crearRegla: (datos) =>
    pedir(MAINT, "/api/v1/mantenimiento/reglas", {
      method: "POST",
      body: JSON.stringify(datos),
    }),

  alertas: (estado = "abierta") =>
    pedir(MAINT, `/api/v1/mantenimiento/alertas${consulta({ estado })}`),

  proximos: (dias = 90) => pedir(MAINT, `/api/v1/mantenimiento/proximos${consulta({ dias })}`),

  programa: (vehiculoId) => pedir(MAINT, `/api/v1/mantenimiento/vehiculo/${vehiculoId}/programa`),

  /** OJO: esta llamada dispara por dentro el REST SÍNCRONO de Maintenance hacia Fleet. */
  ficha: (vehiculoId) => pedir(MAINT, `/api/v1/mantenimiento/vehiculo/${vehiculoId}/ficha`),

  dependencias: () => pedir(MAINT, "/api/v1/mantenimiento/dependencias"),

  /** Cierra el programa, publica maintenance.completed y abre el ciclo preventivo. */
  registrarIntervencion: (datos) =>
    pedir(MAINT, "/api/v1/mantenimiento/intervenciones", {
      method: "POST",
      body: JSON.stringify(datos),
    }),
};

// ------------------------------------------------------ Valores del dominio
// Copiados de los Literal de Pydantic: si el backend los cambia, esto rompe
// primero aquí y no con un 422 delante del usuario.
//
// codigo_obd2 desapareció de la lista (defecto 3.3): el payload lo trae como
// LISTA de códigos ("P0420") y las reglas comparan umbrales numéricos
// (float(valor)), así que una regla con esa métrica jamás podría disparar.

export const TIPOS_VEHICULO = ["tractomula", "camion_rigido", "furgon", "van", "moto"];
export const ESTADOS_VEHICULO = ["disponible", "en_ruta", "mantenimiento", "fuera_servicio"];
export const METRICAS = [
  "temperatura_motor_c",
  "km_acumulados",
  "horas_motor",
  "nivel_combustible_pct",
];
export const ESTADOS_PROGRAMA = [
  "pendiente",
  "programado",
  "en_taller",
  "completado",
  "cancelado",
];
