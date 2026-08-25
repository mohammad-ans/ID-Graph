from pathlib import Path
import yaml
import active_learning

SCHEMA_PATH = Path(__file__).with_name("schema.yaml")

def load_schema():
    with open(SCHEMA_PATH) as file:
        return yaml.safe_load(file)

def display_columns(schema_cols: dict):
    cols = list(schema_cols.get("passthrough", []))
    for group in schema_cols.get("signal_groups", []):
        cols += group["columns"]
    return cols

def fetch_record_details(conn, record_ids: list[str], schema_cols: dict, schema_name: str, sync_table: str):
    if not record_ids:
        return {}
    row = []
    record_id_col = schema_cols["record_id"][0]
    columns = [record_id_col] + display_columns(schema_cols)
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT {', '.join(columns)}
            FROM {schema_name}.{sync_table}
            WHERE {record_id_col} = ANY(%s)
        """, (record_ids))
        rows = cur.fetchall()
    return {row[0]: dict(zip(columns, row)) for row in rows}

def format_record(id: str, details: dict | None, schema_cols: dict):
    if details is None:
        return f"  {id}: No details for this record found"
    return f"  {id} {' '.join(f'{c}={details.get(c)!r}' for c in display_columns(schema_cols))}"

def run_review_session(conn, schema_cols: dict, schema_name: str, sync_table: str, review_table: str = "identity_review_queue", limit: int = 10, print_f = print):
    candidates = active_learning.fetch_review_queue(conn, schema_name, review_table, limit)
    if not candidates:
        print_f("Review queue is empty so nothing to review yet")
    record_ids = sorted({record_id for a, b, _, _ in candidates for record_id in (a, b)})
    details = fetch_record_details(conn, record_ids, schema_cols, schema_name, sync_table)
    recorded = 0
    for record_a, record_b, score, features in candidates:
        print_f("\n" + "=" * 72)
        print_f(format_record(record_a, details.get(record_a), schema_cols))
        print_f(format_record(record_b, details.get(record_b), schema_cols))