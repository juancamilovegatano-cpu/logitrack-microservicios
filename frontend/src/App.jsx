import { useEffect, useState } from "react";

import { fleet, mantenimiento } from "./api.js";
import Conductores from "./componentes/Conductores.jsx";
import Flota from "./componentes/Flota.jsx";
import Mantenimiento from "./componentes/Mantenimiento.jsx";
import Resiliencia from "./componentes/Resiliencia.jsx";

const PESTANAS = [
  { id: "flota", nombre: "Flota", componente: Flota },
  { id: "conductores", nombre: "Conductores", componente: Conductores },
  { id: "mantenimiento", nombre: "Mantenimiento", componente: Mantenimiento },
  { id: "resiliencia", nombre: "Comunicación síncrona", componente: Resiliencia },
];

function Semaforo({ nombre, vivo }) {
  const clase = vivo === null ? "" : vivo ? "ok" : "mal";
  const texto = vivo === null ? "comprobando…" : vivo ? "en línea" : "sin conexión";
  return (
    <span className="pastilla" title={`${nombre}: ${texto}`}>
      <span className={`punto ${clase}`} aria-hidden="true" />
      {nombre}
      <span className="tenue">{texto}</span>
    </span>
  );
}

export default function App() {
  // La pestaña activa sobrevive a un F5: recargar y perder el sitio molesta.
  const [pestana, setPestana] = useState(
    () => localStorage.getItem("logitrack.pestana") || "flota"
  );
  const [saludFleet, setSaludFleet] = useState(null);
  const [saludMant, setSaludMant] = useState(null);

  useEffect(() => {
    try {
      localStorage.setItem("logitrack.pestana", pestana);
    } catch {
      /* navegación privada: no es crítico */
    }
  }, [pestana]);

  // Sondea /ready de los dos servicios cada 10 s. /ready, no /health: el primero
  // solo responde 200 si además hay conexión con la base de datos.
  useEffect(() => {
    let vigente = true;
    const revisar = async () => {
      const [f, m] = await Promise.allSettled([fleet.salud(), mantenimiento.salud()]);
      if (!vigente) return;
      setSaludFleet(f.status === "fulfilled");
      setSaludMant(m.status === "fulfilled");
    };
    revisar();
    const id = setInterval(revisar, 10000);
    return () => {
      vigente = false;
      clearInterval(id);
    };
  }, []);

  const ningunoVivo = saludFleet === false && saludMant === false;
  const Vista = PESTANAS.find((p) => p.id === pestana)?.componente || Flota;

  return (
    <>
      <header className="cabecera-app">
        <div>
          <h1>
            Logi<span>Track</span>
          </h1>
          <div className="sub">Panel de operaciones · Fleet Service + Maintenance Service</div>
        </div>
        <div className="estado-servicios">
          <Semaforo nombre="Fleet" vivo={saludFleet} />
          <Semaforo nombre="Maintenance" vivo={saludMant} />
        </div>
      </header>

      <nav className="tabs">
        {PESTANAS.map((p) => (
          <button
            key={p.id}
            className={pestana === p.id ? "activa" : ""}
            onClick={() => setPestana(p.id)}
          >
            {p.nombre}
          </button>
        ))}
      </nav>

      <main>
        {ningunoVivo && (
          <div className="aviso error" role="alert">
            <span>
              No hay respuesta de ninguno de los dos servicios. Comprueba que los contenedores estén
              arriba: <code className="mono">docker compose ps</code>
            </span>
          </div>
        )}
        <Vista />
      </main>

      <footer className="pie">
        LogiTrack — Momento 1 · 2 de los 10 microservicios del documento de arquitectura (fichas 3.2
        y 3.6)
      </footer>
    </>
  );
}
