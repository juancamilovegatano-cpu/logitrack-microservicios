/**
 * Pestaña Conductores — Fleet Service (ficha 3.2).
 *
 * La regla de disponibilidad no es un campo de la tabla: el backend la calcula
 * cruzando la asignación activa con el tope de 60 h semanales. Por eso aquí se
 * consulta el endpoint en vez de deducirla en el navegador.
 */

import { useState } from "react";

import { fleet } from "../api.js";
import {
  Campo,
  Cargando,
  Error_,
  Etiqueta,
  Id,
  Modal,
  Panel,
  Tabla,
  fechaHora,
  numero,
  useCargar,
} from "../ui.jsx";

const CATEGORIAS = ["A1", "A2", "B1", "B2", "B3", "C1", "C2", "C3"];

function FormularioConductor({ onCerrar, onCreado }) {
  const [nombre, setNombre] = useState("");
  const [licencia, setLicencia] = useState("");
  const [hazmat, setHazmat] = useState(false);
  const [categorias, setCategorias] = useState([]);
  const [error, setError] = useState(null);
  const [enviando, setEnviando] = useState(false);

  const alternar = (categoria) =>
    setCategorias((previo) =>
      previo.includes(categoria) ? previo.filter((c) => c !== categoria) : [...previo, categoria]
    );

  const enviar = async (evento) => {
    evento.preventDefault();
    setEnviando(true);
    setError(null);
    try {
      const creado = await fleet.crearConductor({
        nombre,
        numero_licencia: licencia,
        certificacion_hazmat: hazmat,
        categorias,
      });
      onCreado(creado);
    } catch (fallo) {
      setError(fallo);
      setEnviando(false);
    }
  };

  return (
    <Modal titulo="Nuevo conductor" onCerrar={onCerrar} ancho="560px">
      <form onSubmit={enviar}>
        <Error_ error={error} />
        <div className="rejilla dos">
          <Campo etiqueta="Nombre">
            <input
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              minLength={3}
              maxLength={120}
              required
              autoFocus
            />
          </Campo>
          <Campo etiqueta="Número de licencia" ayuda="Único en el sistema">
            <input
              value={licencia}
              onChange={(e) => setLicencia(e.target.value)}
              minLength={4}
              maxLength={30}
              required
              placeholder="LIC-001"
            />
          </Campo>
        </div>

        <Campo etiqueta="Categorías de licencia">
          <div className="casillas envolver">
            {CATEGORIAS.map((c) => (
              <label key={c}>
                <input
                  type="checkbox"
                  checked={categorias.includes(c)}
                  onChange={() => alternar(c)}
                />
                {c}
              </label>
            ))}
          </div>
        </Campo>

        <label className="conmutador">
          <input type="checkbox" checked={hazmat} onChange={(e) => setHazmat(e.target.checked)} />
          Certificación hazmat
        </label>

        <footer className="acciones-formulario">
          <button type="button" className="boton fantasma" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" className="boton" disabled={enviando}>
            {enviando ? "Creando…" : "Crear conductor"}
          </button>
        </footer>
      </form>
    </Modal>
  );
}

function Disponibilidad({ conductor, onCerrar }) {
  const { datos, cargando, error, recargar } = useCargar(
    () => fleet.disponibilidadConductor(conductor.id),
    [conductor.id]
  );

  return (
    <Modal titulo={`Disponibilidad — ${conductor.nombre}`} onCerrar={onCerrar} ancho="520px">
      {cargando && <Cargando />}
      <Error_ error={error} onReintentar={recargar} />

      {datos && (
        <>
          <div className={`veredicto ${datos.disponible ? "si" : "no"}`}>
            <strong>{datos.disponible ? "Disponible" : "No disponible"}</strong>
            <span>{datos.motivo}</span>
          </div>

          <div className="rejilla datos">
            <div>
              <span className="etiqueta-campo">Horas esta semana</span>
              <span>{numero(datos.horas_conducidas_semana, 1)} h</span>
            </div>
            <div>
              <span className="etiqueta-campo">Horas restantes</span>
              <span>{numero(datos.horas_restantes, 1)} h</span>
            </div>
            <div>
              <span className="etiqueta-campo">Vehículo asignado</span>
              {datos.vehiculo_asignado ? (
                <Id valor={datos.vehiculo_asignado} />
              ) : (
                <span className="tenue">ninguno</span>
              )}
            </div>
            <div>
              <span className="etiqueta-campo">Consultado</span>
              <span className="tenue">{fechaHora(datos.consultado_en)}</span>
            </div>
          </div>

          <p className="descripcion">
            El cálculo vive en el servicio, no aquí: cruza la asignación vigente con el tope legal de
            60 h semanales. El panel solo pregunta.
          </p>
        </>
      )}
    </Modal>
  );
}

export default function Conductores() {
  const [busqueda, setBusqueda] = useState("");
  const [creando, setCreando] = useState(false);
  const [consultando, setConsultando] = useState(null);

  const { datos, cargando, error, recargar } = useCargar(
    () => fleet.listarConductores(busqueda),
    [busqueda]
  );

  const conductores = datos || [];

  return (
    <>
      <Panel
        titulo="Conductores"
        descripcion="Maestro de conductores con sus categorías, certificaciones y horas acumuladas."
        acciones={
          <>
            <button className="boton fantasma" onClick={recargar} disabled={cargando}>
              Actualizar
            </button>
            <button className="boton" onClick={() => setCreando(true)}>
              Nuevo conductor
            </button>
          </>
        }
      >
        <div className="filtros">
          <Campo etiqueta="Nombre">
            <input
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
              placeholder="buscar…"
            />
          </Campo>
        </div>

        <Error_ error={error} onReintentar={recargar} />
        {cargando && <Cargando />}

        {!cargando && !error && (
          <Tabla
            columnas={["Nombre", "Licencia", "Categorías", "Hazmat", "Horas semana", "ID", ""]}
            vacio="No hay conductores registrados. Crea uno o ejecuta scripts/seed.py."
          >
            {conductores.length > 0 &&
              conductores.map((c) => (
                <tr key={c.id}>
                  <td className="fuerte">{c.nombre}</td>
                  <td className="mono">{c.numero_licencia}</td>
                  <td>
                    {c.categorias.length > 0 ? (
                      c.categorias.map((cat) => (
                        <span key={cat} className="etiqueta gris">
                          {cat}
                        </span>
                      ))
                    ) : (
                      <span className="tenue">—</span>
                    )}
                  </td>
                  <td>
                    {c.certificacion_hazmat ? (
                      <Etiqueta valor="hazmat" tono="morado" />
                    ) : (
                      <span className="tenue">no</span>
                    )}
                  </td>
                  <td>{numero(c.horas_conducidas_semana, 1)} h</td>
                  <td>
                    <Id valor={c.id} />
                  </td>
                  <td className="acciones-fila">
                    <button className="boton menor" onClick={() => setConsultando(c)}>
                      Disponibilidad
                    </button>
                  </td>
                </tr>
              ))}
          </Tabla>
        )}
      </Panel>

      {creando && (
        <FormularioConductor
          onCerrar={() => setCreando(false)}
          onCreado={() => {
            setCreando(false);
            recargar();
          }}
        />
      )}

      {consultando && (
        <Disponibilidad conductor={consultando} onCerrar={() => setConsultando(null)} />
      )}
    </>
  );
}
