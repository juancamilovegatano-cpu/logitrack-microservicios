from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "maintenance-service"
    database_url: str = "postgresql+psycopg2://logitrack:logitrack@localhost:5433/maintenance_db"
    rabbitmq_url: str = "amqp://logitrack:logitrack@localhost:5672/"

    # Exchange ÚNICO del sistema (ver nota en fleet-service/app/config.py).
    exchange_eventos: str = "logitrack.events"

    queue_name: str = "maintenance.inbox"
    dlx_name: str = "logitrack.dlx"

    outbox_poll_seconds: float = 2.0
    outbox_batch_size: int = 100
    events_enabled: bool = True

    # Orígenes del frontend autorizados a llamar esta API desde el navegador
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]

    # Ventana de "próximo mantenimiento" por defecto en días
    dias_proximos_default: int = 90

    # --- Comunicación REST SÍNCRONA hacia Fleet (sección 05 del documento) ---
    fleet_base_url: str = "http://localhost:8001"
    # Timeout: 2 s para llamadas REST internas
    rest_timeout_segundos: float = 2.0
    # Reintentos: máximo 3 intentos con retroceso exponencial 1 s, 2 s, 4 s
    rest_max_intentos: int = 3
    rest_backoff_base_segundos: float = 1.0
    rest_jitter_maximo_segundos: float = 0.3
    # Circuit breaker: 5 fallos en 30 s abren; tras 30 s pasa a semiabierto
    breaker_umbral_fallos: int = 5
    breaker_ventana_segundos: float = 30.0
    breaker_espera_abierto_segundos: float = 30.0


settings = Settings()
