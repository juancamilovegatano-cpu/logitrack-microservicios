from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def aplicar_ajustes_pendientes(engine) -> None:
    """Ajustes de esquema que create_all NO aplicaría a tablas ya existentes.

    APAÑO mientras el grupo decide cuándo adopta Alembic (el README lo deja
    para el "momento 2"): create_all solo crea tablas que faltan, nunca añade
    columnas a tablas existentes, así que una base que ya corre necesitaría
    esto para recibir la columna event_id. Transacción única: o entran todos
    los pasos o ninguno. Todas las sentencias son idempotentes (IF NOT EXISTS),
    por lo que en una base nueva son un no-op tras el create_all.
    """
    with engine.begin() as conexion:
        # 1) añadir la columna (nullable de momento, para poder rellenarla)
        conexion.execute(
            text(
                "ALTER TABLE outbox_eventos "
                "ADD COLUMN IF NOT EXISTS event_id UUID"
            )
        )
        # 2) rellenar las filas existentes con un uuid estable cada una
        conexion.execute(
            text(
                "UPDATE outbox_eventos "
                "SET event_id = gen_random_uuid() "
                "WHERE event_id IS NULL"
            )
        )
        # 3) único índice: dos filas no pueden compartir event_id
        conexion.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_outbox_eventos_event_id "
                "ON outbox_eventos (event_id)"
            )
        )
        # 4) ya con datos: la columna puede ser NOT NULL
        conexion.execute(
            text("ALTER TABLE outbox_eventos ALTER COLUMN event_id SET NOT NULL")
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
