from __future__ import annotations
import logging, sys, time
from config import NebulaConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


CONNECT_RETRY_SECONDS = 5
CONNECT_MAX_ATTEMPTS = 24
HOST_ONLINE_RETRY_SECONDS = 3
HOST_ONLINE_MAX_ATTEMPTS = 40
STORAGE_HOST = "storaged"
STORAGE_PORT = 9779

def connect_retry(config: NebulaConfig):
    from nebula3.Config import Config
    from nebula3.gclient.net import ConnectionPool

    pool_config = Config()
    pool_config.max_connection_pool_size = 2
    pool = ConnectionPool()

    for attempt in range(1, CONNECT_MAX_ATTEMPTS + 1):
        initialized = pool.init([(config.host, config.port)], pool_config)
        if initialized:
            logger.info("Connected to Nebula graphd at %s:%s (attempt %s)", config.host, config.port, attempt)
            return pool
        logger.info("Graphd not reachable yet at %s:%s (attempt %s%s) -- retrying in %ss", config.host, config.port, attempt, CONNECT_MAX_ATTEMPTS, CONNECT_RETRY_SECONDS)
        time.sleep(CONNECT_RETRY_SECONDS)
    raise RuntimeError(f"Could not connect to nebula graphd at {config.host}:{config.port} after {CONNECT_MAX_ATTEMPTS} attempts")

def add_storage_host(session):
    result = session.execute(f'ADD HOSTS "{STORAGE_HOST}":{STORAGE_PORT};')
    if result.is_succeeded():
        logger.info("Registered storage host: %s:%s", STORAGE_HOST, STORAGE_PORT)
    msg = result.error_msg() or ""
    if "existed" in msg.lower():
        logger.info("Storage host %s:%s was already registered", STORAGE_HOST, STORAGE_PORT)
        return
    raise RuntimeError(f"Add host failed: {msg}")

def wait_for_host(session):
    for attempt in range(1, HOST_ONLINE_MAX_ATTEMPTS + 1):
        result = session.execute("SHOW HOSTS;")
        if not result.is_succeeded():
            raise RuntimeError(f"Show hosts failed: {result.error_msg()}")
        for i in range(result.row_size()):
            row = [v.cast() for v in result.row_values(i)]
            host, port, status = row[0], row[1], row[2]
            if str(host) == STORAGE_HOST and int(port) == STORAGE_PORT:
                if str(status).upper() == "ONLINE":
                    logger.info("Storage host %s:%s is ONLINE", STORAGE_HOST, STORAGE_PORT)
                    return
                logger.info("Storage host %s:%s status=%s (attempt %s / %s). Waiting %ss", STORAGE_HOST, STORAGE_PORT, status, attempt, HOST_ONLINE_MAX_ATTEMPTS, HOST_ONLINE_RETRY_SECONDS)
                break
        else:
            logger.info("Storage host %s:%s not listed yet by SHOW HOSTS (attempt %s / %s). Waiting%ss", STORAGE_HOST, STORAGE_PORT, attempt, HOST_ONLINE_MAX_ATTEMPTS, HOST_ONLINE_RETRY_SECONDS)
        time.sleep(HOST_ONLINE_RETRY_SECONDS)
    raise RuntimeError(f"Storage host {STORAGE_HOST}:{STORAGE_PORT} did not report ONLINE after {HOST_ONLINE_MAX_ATTEMPTS} attempts. Check logs for errors.")

def main():
    config = NebulaConfig.from_env()
    pool = connect_retry(config)
    session = pool.get_session(config.username, config.password)
    try:
        add_storage_host(session)
        wait_for_host(session)
        logger.info("Nebula cluster initialization complete. Now schema files can be ran on it")
    finally:
        session.release()
        pool.close()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error("Initializing nebula failed: %s", e)
        sys.exit(1)