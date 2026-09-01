from __future__ import annotations
import logging
from .config import PostgresConfig

logger = logging.getLogger(__name__)

__all__ = ["connect_postgres"]

def connect_postgres(config: PostgresConfig):
    import psycopg2
    logger.info("Openning postgres connection %s:%s%s", config.host, config.port, config.dbname)
    return psycopg2.connect(host=config.host, port=config.port, dbname=config.dbname, user=config.user, password=config.password, connect_timeout=config.connect_timeout, keepalives=1, keepalives_idle=60, keepalives_interval=10, keepalives_count=5)