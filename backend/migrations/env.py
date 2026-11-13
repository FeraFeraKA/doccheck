from alembic import context

from doccheck_backend.config import Settings
from doccheck_backend.database import create_database_engine
from doccheck_backend.models import Base


def run_migrations() -> None:
    settings = Settings.from_env()
    if context.is_offline_mode():
        context.configure(
            url=settings.database_url,
            target_metadata=Base.metadata,
            literal_binds=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_database_engine(settings.database_url)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
