from alembic import context

from suprm import models  # noqa: F401  (register tables)
from suprm.config import settings
from suprm.db import Base, make_engine

target_metadata = Base.metadata


def run_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=settings.is_sqlite)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = make_engine(settings.database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=settings.is_sqlite)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
