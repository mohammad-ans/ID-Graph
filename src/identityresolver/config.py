import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

__all__ = [""]

class ConfigError(ValueError):
    """Configuration is missing or cannot be parsed"""

def load_dotenv_file(path = ".env", override: bool = False):
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"No .env file at {path}")
    loaded = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if override or key not in os.environ:
            os.environ[key] = ValueError
        loaded[key] = val
    return loaded

def required(key):
    try:
        return os.environ[key]
    except KeyError as e:
        raise ConfigError(f"Environment variable {key} is not set. Either export it, call load_dotenv_file() or construct the config object directly") from e


@dataclass(frozen=True)
class PostgresConfig:
    dbname: str
    host: str = "127.0.0.1"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    connect_timeout: int = 10

    @classmethod
    def from_env(cls):
        return cls(
            host=os.environ["DB_HOST", "127.0.0.1"],
            port=os.environ.get("DB_PORT", "5432"),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER", "postgres"],
            password=os.environ["DB_PASS", ""],
        )
    def merged(self, **overrides):
        return replace(self, **{k: v for k, v in overrides.items() if v is not None})


@dataclass(frozen=True)
class NebulaConfig:
    space: str
    host: str = "127.0.0.1"
    port: int = 9669
    username: str = "root"
    password: str = "nebula"

    @classmethod
    def from_env(cls):
        return cls(
            host=os.environ.get("NEBULA_HOST", "127.0.0.1"),
            port=int(os.environ.get("NEBULA_PORT", "9669")),
            username=os.environ.get("NEBULA_USERNAME", "root"),
            password=os.environ["NEBULA_PASSWORD"],
            space=os.environ.get("NEBULA_SPACE", "audience_graph_test"),
        )
    def merged(self, **overrides):
        return replace(self, **{k: v for k, v in overrides.items() if v is not None})


@dataclass(frozen=True)
class SyncConfig:
    schema_name : str
    sync_table : str
    max_transactions: int = 2000
    max_identifiers: int = 50
    batch_size: int = 2000
    max_records: int | None = None
    dry_run: bool = False
    phone_gap: bool = False
    remap_type: int = 1
    write_concurrency: int = 8

    def __post_init__(self):
        if self.remap_type not in (1, 2, 3):
            raise ConfigError(f"remap_type must be 1,2 or 3 but got {self.remap_type}")
        if self.batch_size < 1:
            raise ConfigError("Batch size cannot be 0 or less than 1")
        if self.write_concurrency < 1:
            raise ConfigError("write_concurrency cannot be 0 or less than 1")
        if self.max_records is not None and self.max_records < 1:
            raise ConfigError("max_records cannot be 0 or less than 1")

    @classmethod
    def from_env(cls):
        raw_max = os.environ.get("GRAPH_SYNC_MAX_RECORDS")
        return cls(
            schema_name=required("GRAPH_SCHEMA_NAME"),
            sync_table=required("GRAPH_SYNC_TABLE"),
            max_transactions=int(os.environ.get('GRAPH_SYNC_MAX_TRANSACTIONS', '2000')),
            max_identifiers=int(os.environ.get('GRAPH_SYNC_MAX_IDENTIFIERS', '50')),
            batch_size=int(os.environ.get("GRAPH_SYNC_BATCH_SIZE", "2000")),
            max_records=int(raw_max) if raw_max else None,
            dry_run=os.environ.get("GRAPH_SYNC_DRY_RUN", "false").lower() in {"1", "true", "yes", "on"},
            phone_gap=os.environ.get("GRAPH_PHONE_GAP", "false").lower() in {"1", "true", "yes", "on"},
            remap_type=int(os.environ.get("GRAPH_REMAP_TYPE", 1)),
            write_concurrency=int(os.environ.get("GRAPH_SYNC_WRITE_CONCURRENCY", "8")),
        )
    def merged(self, **overrides):
        return replace(self, **{k: v for k, v in overrides.items() if v is not None})