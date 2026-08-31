from __future__ import annotations
import argparse, csv, json
import os, sys, re
import logging
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent / "main"
sys.path.insert(0, str(MAIN_DIR))

from config import PostgresConfig
from sync_audience_graph import connect_postgres

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
COLUMN_RE = re.compile(r"[^a-z0-9_]+")
ALLOWED = {"text", "integer", "bigint", "numeric", "real", "boolean", "date", "timestamp", "jsonb", "uuid", "smallint", "double precision", "timestamptz"}

def normalize_name(col):
    name = col.strip().lower()
    name = COLUMN_RE.sub("_", name).strip("_")
    if not name:
        raise ValueError(f"Column name {col!r} normalizes to empty name")
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

def build_column_plan(header: list[str], column_types: dict[str, str] | None):
    column_types = column_types or {}
    plan = []
    seen = set()
    for col_name in header:
        pg_col = normalize_name(col_name)
        if pg_col in seen:
            raise ValueError("Two csv columns have same name, ofc a database cannot have that")
        seen.add(pg_col)
        if pg_col in column_types:
            pg_type  = column_types[pg_col]
        elif col_name in column_types:
            pg_type = column_types[col_name]
        else:
            pg_type = "text"
        
        if pg_type not in ALLOWED:
            raise ValueError(f"Unknown column type {pg_type}")
        plan.append((col_name, pg_col, pg_type))

    return plan

def create_table(conn, schema_name, table_name, column_plan):
    identifier_validation(schema_name, "schema name")
    identifier_validation(table_name, "table name")
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {schema_name}.{table_name};")
        columns = ", ".join(f'"{col}" {type_}' for _, col, type_ in column_plan)
        cur.execute(f"CREATE TABLE {schema_name}.{table_name} ({columns});")
    conn.commit()
    logger.info(f"Dropped any existing table with that name and created table {schema_name}.{table_name}")

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
    logger.info(f"Loaded {count} rows into {schema_name}.{table_name}")
    return count

def load_csv(conn, path: Path, schema_name, table_name, column_types, primary_key):
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
    create_table(conn, schema_name, table_name, column_plan)
    count = copy_data(conn, path, schema_name, table_name, column_plan)
    if pk_col:
        add_primary_key(conn, schema_name, table_name, pk_col)
    return count

def add_primary_key(conn, schema_name, table_name, primary_key):
    identifier_validation(primary_key, "primary key column")
    with conn.cursor() as cur:
        cur.execute(f'ALTER TABLE {schema_name}.{table_name} ADD PRIMARY KEY ("{primary_key}");')
    conn.commit()
    logger.info(f"Setted {primary_key} as the primary key")

def main():
    parser = argparse.ArgumentParser(description="Load csv into postgres")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--table", default=None)
    parser.add_argument("--schema-name", default=None)
    parser.add_argument("--column-types", default=None)
    parser.add_argument("--primary-key", required=True)
    args = parser.parse_args()
    schema_name = args.schema_name or os.environ.get("GRAPH_SCHEMA_NAME")
    if not schema_name:
        print("No schema name given")
        sys.exit(1)
    table_name = args.table or os.environ.get("GRAPH_SYNC_TABLE")
    if not table_name:
        print("No table name given")
        sys.exit(1)
    if args.column_types:
        with open(args.column_types) as file:
            column_types = json.load(file)
    conn = connect_postgres(PostgresConfig.from_env())
    conn.cursor().execute(f"DROP SCHEMA {schema_name} CASCADE; CREATE SCHEMA {schema_name}")
    try:
        count = load_csv(conn, Path(args.csv), schema_name, table_name, column_types, args.primary_key)
        print(f"Loaded the csv successfully into the db with {count} rows")
    finally:
        conn.close()
if __name__ == "__main__":
    main()