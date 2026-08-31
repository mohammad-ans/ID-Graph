from __future__ import annotations
import csv, re
import logging
from pathlib import Path

from .config import PostgresConfig

logger = logging.getLogger(__name__)

__all__ = ["load_csv_file", "load_csv", "normalize_name", "build_column_plan", "read_csv_header", "ALLOWED_TYPES"]

IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
COLUMN_RE = re.compile(r"[^a-z0-9_]+")

ALLOWED = frozenset({ "text", "integer", "bigint", "smallint", "numeric", "real", "double precision", "boolean", "date", "timestamp", "timestamptz", "jsonb", "uuid"})


def normalize_name(col):
    name = col.strip().lower()
    name = COLUMN_RE.sub("_", name).strip("_")
    if not name:
        raise ValueError(f"Column name {col!r} normalizes to an empty name")
    if name[0].isdigit():
        name = "col_" + name
    return name

def identifier_validation(name: str, type_: str):
    if not IDENTIFIER_RE.match(name):
        raise ValueError(f"{name!r} {type_} is not a safe postgres identifier")
    return name

def read_csv_header(csv_path: Path):
    with open(csv_path, newline="", encoding="utf-8-sig") as file:
        try:
            return next(csv.reader(file))
        except StopIteration:
            raise ValueError(f"{csv_path} is empty, no header row to read")

def build_column_plan(header: list[str], column_types: dict[str, str] | None = None):
    column_types = column_types or {}
    plan = []
    seen = set()
    for col_name in header:
        pg_col = normalize_name(col_name)
        if pg_col in seen:
            raise ValueError(f"Two csv columns have same name, ofc a database cannot have that{pg_col!r}")
        seen.add(pg_col)
        if pg_col in column_types:
            pg_type = column_types[pg_col]
        elif col_name in column_types:
            pg_type = column_types[col_name]
        else:
            pg_type = "text"
        
        if pg_type not in ALLOWED:
            raise ValueError(f"Unknown column type {pg_type!r} for {col_name!r}. Allowed types: {', '.join(sorted(ALLOWED))}")
        plan.append((col_name, pg_col, pg_type))
    return plan

def ensure_schema(conn, schema_name: str):
    identifier_validation(schema_name, "schema name")
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name};")
    conn.commit()
    logger.info("Schema %s is present", schema_name)


def create_table(conn, schema_name: str, table_name: str, column_plan, replace: bool = False):
    identifier_validation(schema_name, "schema name")
    identifier_validation(table_name, "table name")
    columns = ", ".join(f'"{column}" {pg_type}' for _, column, pg_type in column_plan)
    with conn.cursor() as cur:
        if replace:
            cur.execute(f"DROP TABLE IF EXISTS {schema_name}.{table_name};")
            logger.warning("Dropped existing table %s.%s", schema_name, table_name)
        cur.execute(f"CREATE TABLE {schema_name}.{table_name} ({columns});")
    conn.commit()
    logger.info("Created table %s.%s", schema_name, table_name)

def copy_data(conn, path: Path, schema_name, table_name, column_plan):
    columns = ", ".join(f'"{col}"' for _, col, _ in column_plan)
    with open(path, newline="", encoding="utf-8-sig") as file:
        with conn.cursor() as cur:
            sql = (f"COPY {schema_name}.{table_name} ({columns}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL ' ')")
            cur.copy_expert(sql, file)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {schema_name}.{table_name};")
        (count,) = cur.fetchone()
    logger.info("Loaded %s rows into %s.%s", count, schema_name, table_name)
    return count


def add_primary_key(conn, schema_name: str, table_name: str, primary_key: str) -> None:
    identifier_validation(primary_key, "primary key column")
    with conn.cursor() as cur:
        cur.execute(
            f'ALTER TABLE {schema_name}.{table_name} ADD PRIMARY KEY ("{primary_key}");'
        )
    conn.commit()
    logger.info("Set %s as the primary key of %s.%s", primary_key, schema_name, table_name)

def load_csv(conn, path: str | Path, schema_name: str, table_name: str, primary_key: str, column_types: dict[str, str] | None = None, replace: bool = False, create_schema: bool = True):
    path = Path(path)
    header = read_csv_header(path)
    column_plan = build_column_plan(header, column_types)
    pk_col = None
    if primary_key:
        pg_cols = {col for _, col, _ in column_plan}
        cols = {col for col, _, _ in column_plan}
        if primary_key in pg_cols:
            pk_col = primary_key
        elif primary_key in cols:
            pk_col = {pg_col for col_name, pg_col, _ in column_plan if col_name == primary_key}
        else:
            raise ValueError(f"{primary_key!r} does not matches any normalized or simple column name in csv header")
    if create_schema:
        ensure_schema(conn, schema_name)
    create_table(conn, schema_name, table_name, column_plan, replace=replace)
    count = copy_data(conn, path, schema_name, table_name, column_plan)
    if pk_col:
        add_primary_key(conn, schema_name, table_name, pk_col)
    else:
        raise ValueError(f"No primary key found in csv file, neither as normalized or simple match. key: {primary_key}")
    return count


def load_csv_file(path: str | Path, schema_name: str, table_name: str, primary_key: str, pg_config: PostgresConfig, column_types: dict[str, str] | None = None, replace: bool = False, create_schema: bool = True):
    from .postgres import connect_postgres
    conn = connect_postgres(pg_config)
    try:
        return load_csv(conn, path, schema_name, table_name, primary_key, column_types=column_types,replace=replace, create_schema=create_schema)
    finally:
        conn.close()