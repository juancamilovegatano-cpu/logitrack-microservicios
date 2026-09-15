from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "fleet-service"
    database_url: str = "postgresql+psycopg2://logitrack:logitrack@localhost:5432/fleet_db"
    rabbitmq_url: str = "amqp://logitrack:logitrack@localhost:5672/"

    # Exchange propio (dominio fleet) donde este servicio PUBLICA
    exchange_propio: str = "logitrack.fleet"
    # Exchanges ajenos de los que este servicio CONSUME
    exchange_maintenance: str = "logitrack.maintenance"
    exchange_shipment: str = "logitrack.shipment"

    queue_name: str = "fleet.inbox"
    dlx_name: str = "logitrack.dlx"

    outbox_poll_seconds: float = 2.0
    outbox_batch_size: int = 100
    events_enabled: bool = True


settings = Settings()
