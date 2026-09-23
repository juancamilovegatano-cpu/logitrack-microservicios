from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "fleet-service"
    database_url: str = "postgresql+psycopg2://logitrack:logitrack@localhost:5432/fleet_db"
    rabbitmq_url: str = "amqp://logitrack:logitrack@localhost:5672/"

    # Exchange ÚNICO del sistema: todos publican y consumen aquí, y la
    # routing key es el `event_type`. Antes había un exchange por dominio
    # (logitrack.fleet, .maintenance, .shipment); se unificó para que los
    # cinco microservicios hablen un solo contrato y no haga falta un
    # traductor entre dialectos.
    exchange_eventos: str = "logitrack.events"

    queue_name: str = "fleet.inbox"
    dlx_name: str = "logitrack.dlx"

    outbox_poll_seconds: float = 2.0
    outbox_batch_size: int = 100
    events_enabled: bool = True

    # Orígenes del frontend autorizados a llamar esta API desde el navegador
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]


settings = Settings()
