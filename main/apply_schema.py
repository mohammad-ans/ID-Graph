from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from config import NebulaConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


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
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return [s for s in statements if s]


def execute_or_raise(session, statement: str):
    result = session.execute(statement)
    if not result.is_succeeded():
        raise RuntimeError(f"Nebula query failed: {result.error_msg()}\nStatement:\n{statement}")
    return result


def parse_args():
    parser = argparse.ArgumentParser(description="Create/update the Nebula audience graph schema.")
    parser.add_argument(
        "--schema-file",
        default=str(Path(__file__).with_name("schema.ngql")),
        help="Path to an nGQL schema file.",
    )
    parser.add_argument(
        "--space-create-wait-seconds",
        type=int,
        default=10,
        help="Wait after CREATE SPACE so the new space is visible before USE.",
    )
    return parser.parse_args()


def main():
    try:
        from nebula3.Config import Config
        from nebula3.gclient.net import ConnectionPool
    except ImportError as exc:
        raise RuntimeError(
            "nebula3-python is required for graph schema bootstrap. Install it in the job image "
            "with `pip install nebula3-python`."
        ) from exc

    args = parse_args()
    config = NebulaConfig.from_env()
    statements = split_ngql(Path(args.schema_file).read_text())
    logger.info(
        "Loaded Nebula schema file: path=%s statements=%s target=%s:%s/%s",
        args.schema_file,
        len(statements),
        config.host,
        config.port,
        config.space,
    )

    pool_config = Config()
    pool_config.max_connection_pool_size = 2
    pool = ConnectionPool()
    ok = pool.init([(config.host, config.port)], pool_config)
    if not ok:
        raise RuntimeError(f"Failed to initialize Nebula connection pool for {config.host}:{config.port}")

    session = pool.get_session(config.username, config.password)
    try:
        for idx, statement in enumerate(statements, start=1):
            logger.info("Applying schema statement %s/%s: %s", idx, len(statements), statement.splitlines()[0][:120])
            execute_or_raise(session, statement)
            if statement.upper().startswith("CREATE SPACE"):
                logger.info("Waiting %s seconds for Nebula space propagation", args.space_create_wait_seconds)
                time.sleep(args.space_create_wait_seconds)
    finally:
        session.release()
        pool.close()
    logger.info("Nebula schema apply complete")


if __name__ == "__main__":
    main()
