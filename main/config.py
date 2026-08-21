import os
from dataclasses import dataclass

@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: str
    dbname: str
    user: str
    password: str

    @classmethod
    def from_env(cls):
        return cls(
            host=os.environ["DB_HOST"],
            port=os.environ.get("DB_PORT", "5432"),
            dbname=os.environ["DB_NAME"],
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASS"],
        )


@dataclass(frozen=True)
class NebulaConfig:
    host: str
    port: int
    username: str
    password: str
    space: str

    @classmethod
    def from_env(cls):
        return cls(
            host=os.environ.get(
                "NEBULA_HOST"
            ),
            port=int(os.environ.get("NEBULA_PORT", "9669")),
            username=os.environ.get("NEBULA_USERNAME", "root"),
            password=os.environ["NEBULA_PASSWORD"],
            space=os.environ.get("NEBULA_SPACE", "audience_graph_test"),
        )


@dataclass(frozen=True)
class SyncConfig:
    max_transactions: int
    max_identifiers: int
    batch_size: int
    max_records: int | None
    dry_run: bool
    phone_gap: bool
    remap_type: int
    schema_name : str
    sync_table : str
    write_concurrency: int = 8

    @classmethod
    def from_env(cls):
        raw_max = os.environ.get("GRAPH_SYNC_MAX_RECORDS")
        return cls(
            max_transactions=int(os.environ.get('GRAPH_SYNC_MAX_TRANSACTIONS', '2000')),
            max_identifiers=int(os.environ.get('GRAPH_SYNC_MAX_IDENTIFIERS', '50')),
            batch_size=int(os.environ.get("GRAPH_SYNC_BATCH_SIZE", "2000")),
            max_records=int(raw_max) if raw_max else None,
            dry_run=os.environ.get("GRAPH_SYNC_DRY_RUN", "false").lower() in {"1", "true", "yes"},
            phone_gap=os.environ.get("GRAPH_PHONE_GAP", "false").lower() in {"1", "true", "yes"},
            remap_type=int(os.environ.get("GRAPH_REMAP_TYPE", 1)),
            schema_name=os.environ.get("GRAPH_SCHEMA_NAME"),
            sync_table=os.environ.get("GRAPH_SYNC_TABLE"),
            write_concurrency=int(os.environ.get("GRAPH_SYNC_WRITE_CONCURRENCY", "8")),
        )