from __future__ import annotations
import argparse, csv, json
import os, sys
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent / "main"
sys.path.insert(0, str(MAIN_DIR))

from config import PostgresConfig
from sync_audience_graph import connect_postgres

ALLOWED = {"text", "integer", "bigint", "numeric", "real", "boolean", "date", "timestamp", "jsonb", "uuid"}

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
    for col in header:
        if col in seen:
            raise ValueError("Two csv columns have same name, ofc a database cannot have that")
        seen.add(col)
        if col in column_types:
            pg_type = column_types[col]
        elif col in column_types:
            pg_type = "text", None
        if pg_type not in ALLOWED:
            raise ValueError(f"Unknown column type")
        plan.append((col, col, pg_type))
    return plan

def create_table(conn, schema_name, table_name, column_plan):
    with conn.cursor() as cur:
        columns = ", ".join(f'"{col}" {type_}' for _, col, type_ in column_plan)
        cur.execute(f"CREATE TABLE {schema_name}.{table_name} ({columns});")
    conn.commit()

def copy_data(conn, path: Path, schema_name, table_name, column_plan):
    columns = ", ".join(f'"{col}"' for _, col, _ in column_plan)
    with open(path, newline="", encoding="utf-8-sig") as file:
        with conn.cursor() as cur:
            sql = (f"COPY {schema_name}.{table_name} ({columns}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')")
            cur.copy_export(sql, file)
        conn.commit()

def load_csv(conn, path: Path, schema_name, table_name, column_types):
    header = read_csv_header(path)
    column_plan = build_column_plan(header, column_types)
    create_table(conn, schema_name, table_name, column_plan)
    copy_data(conn, path, schema_name, table_name, column_plan)

def main():
    parser = argparse.ArgumentParser(description="Load csv into postgres")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--table", default=None)
    parser.add_argument("--schema-name", default=None)
    parser.add_argument("--column-types", default=None)
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
        with open(args.column_type) as file:
            column_types = json.load(file)
    conn = connect_postgres(PostgresConfig.from_env())
    try:
        load_csv(conn, Path(args.csv), schema_name, table_name, column_types)
        print("Loaded the csv successfully into the db")
    finally:
        conn.close()
if __name__ == "__main__":
    main()