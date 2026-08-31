from __future__ import annotations

import logging, time
from pathlib import Path
from .config import NebulaConfig
from .schema_gen import generate_schema_ngql

logger = logging.getLogger(__name__)

__all__ = ["apply_schema", "split_ngql"]


def split_ngql(script: str) -> list[str]:
    statements = []
    buffer = []
    in_string = False
    i = 0
    n = len(script)
    while i < n:
        ch = script[i]
        if ch == '"' and (i == 0 or script[i - 1] != "\\"):
            in_string = not in_string
            buffer.append(ch)
        elif not in_string and (script[i: i + 2] in ("--", "//") or ch == "#"):
            while i < n and script[i] != "\n":
                i += 1
            continue
        elif not in_string and ch == ";":
            statements.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(ch)
        i += 1
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return [s for s in statements if s]


def _execute_or_raise(session, statement: str):
    result = session.execute(statement)
    if not result.is_succeeded():
        raise RuntimeError(f"Nebula query failed: {result.error_msg()}\nStatement:\n{statement}")
    return result


def apply_schema(nebula_config: NebulaConfig, schema_cols: dict | None = None, ngql_file: str | Path | None = None, drop_existing: bool = False, space_create_wait_seconds: int = 10) -> int:
    try:
        from nebula3.Config import Config
        from nebula3.gclient.net import ConnectionPool
    except ImportError as exc:
        raise RuntimeError(
            "nebula3-python is required for graph schema. "
            "Install it with `pip install nebula3-python`."
        ) from exc

    if (schema_cols is None) == (ngql_file is None):
        raise ValueError("Pass exactly one of schema_cols or ngql_file")

    if ngql_file is not None:
        statements = split_ngql(Path(ngql_file).read_text(encoding="utf-8"))
        logger.info(
            "Loaded static Nebula schema file: path=%s statements=%s target=%s:%s/%s",
            ngql_file, len(statements), nebula_config.host, nebula_config.port, nebula_config.space,
        )
    else:
        statements = generate_schema_ngql(schema_cols, nebula_config.space, drop_existing=drop_existing)
        logger.info("Generated Nebula schema from column schema: statements=%s target=%s:%s/%s", len(statements), nebula_config.host, nebula_config.port, nebula_config.space)

    pool_config = Config()
    pool_config.max_connection_pool_size = 2
    pool = ConnectionPool()
    if not pool.init([(nebula_config.host, nebula_config.port)], pool_config):
        raise RuntimeError(f"Failed to initialize Nebula connection pool for {nebula_config.host}:{nebula_config.port}")

    session = pool.get_session(nebula_config.username, nebula_config.password)
    try:
        for index, statement in enumerate(statements, start=1):
            logger.info("Applying schema statement %s/%s: %s", index, len(statements), statement.splitlines()[0][:120])
            _execute_or_raise(session, statement)
            if statement.upper().lstrip().startswith("CREATE SPACE"):
                logger.info("Waiting %ss for Nebula space propagation", space_create_wait_seconds)
                time.sleep(space_create_wait_seconds)
    finally:
        session.release()
        pool.close()
    logger.info("Nebula schema apply complete")
    return len(statements)