from sqlalchemy import Engine, create_engine


def create_database_engine(database_url: str) -> Engine:
    """Bound connection waits; preserve URL options used for isolated test schemas."""
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_timeout=3,
        connect_args={"connect_timeout": 3},
        hide_parameters=True,
    )
