from __future__ import annotations

import logging

from .config import NebulaConfig

logger = logging.getLogger(__name__)


class NebulaClient:

    def __init__(self, config: NebulaConfig, pool_size: int = 10):
        self.config = config
        self._pool_size = pool_size
        self._pool = None

    def __enter__(self) -> "NebulaClient":
        try:
            from nebula3.Config import Config
            from nebula3.gclient.net import ConnectionPool
        except ImportError as exc:
            raise RuntimeError(
                "nebula3-python is required for graph sync. Install it in the job image "
                "with `pip install nebula3-python`."
            ) from exc

        pool_config = Config()
        pool_config.max_connection_pool_size = max(self._pool_size, 10)
        self._pool = ConnectionPool()
        logger.info(
            "Initializing Nebula connection pool: host=%s port=%s space=%s pool_size=%s",
            self.config.host,
            self.config.port,
            self.config.space,
            pool_config.max_connection_pool_size,
        )
        ok = self._pool.init([(self.config.host, self.config.port)], pool_config)
        if not ok:
            raise RuntimeError(f"Failed to initialize Nebula connection pool for {self.config.host}:{self.config.port}")

        self.execute(f"USE {self.config.space}")
        logger.info("Nebula connection pool ready for space %s", self.config.space)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._pool:
            logger.info("Closing Nebula connection pool for space %s", self.config.space)
            self._pool.close()

    def _checkout_session(self):
        session = self._pool.get_session(self.config.username, self.config.password)
        session.execute(f"USE {self.config.space}")
        return session

    def execute(self, statement: str):
        if not statement.strip():
            return None
        session = self._checkout_session()
        try:
            result = session.execute(statement)
            if not result.is_succeeded():
                raise RuntimeError(f"Nebula query failed: {result.error_msg()}\nStatement:\n{statement[:2000]}")
            return result
        finally:
            session.release()

    def execute_many(self, statements: list[str], chunk_size: int = 100):
        if not statements:
            return
        logger.debug("Executing %s Nebula statements with chunk_size=%s", len(statements), chunk_size)
        session = self._checkout_session()
        try:
            for idx in range(0, len(statements), chunk_size):
                chunk = statements[idx:idx + chunk_size]
                for statement in chunk:
                    if not statement.strip():
                        continue
                    result = session.execute(statement)
                    if not result.is_succeeded():
                        raise RuntimeError(
                            f"Nebula query failed: {result.error_msg()}\nStatement:\n{statement[:2000]}"
                        )
        finally:
            session.release()
