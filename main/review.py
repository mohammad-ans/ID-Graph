from pathlib import Path
import yaml, os, sys, argparse
import main.active_learning as active_learning
from main.sync_audience_graph import connect_postgres
from main.config import PostgresConfig

SCHEMA_PATH = Path(__file__).with_name("cschema.yaml")

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
        """, (record_ids, ))
        rows = cur.fetchall()
    return {row[0]: dict(zip(columns, row)) for row in rows}

def format_record(id: str, details: dict | None, schema_cols: dict):
    if details is None:
        return f"  {id}: No details for this record found"
    return f"  {id} {' '.join(f'{c}={details.get(c)!r}' for c in display_columns(schema_cols))}"

def decide(score: float, features: dict):
    print(f"\n current score{score:.4f} agreement features={features}")
    while True:
        choice = input(" match / not match / skip / quit > ").strip().lower()
        match choice:
            case "match" | "m":
                return "match"
            case "n" | "not match":
                return "not_match"
            case "s" | "skip":
                return "skip"
            case "q" | "quit":
                return "quit"
            case _:
                print("Valid choices are m, n, s, q  and  match, non match, skip, quit")

def record_decisions(conn, schema_cols: dict, schema_name: str, sync_table: str, review_table: str = "identity_review_queue", limit: int = 10):
    candidates = active_learning.fetch_review_queue(conn, schema_name, review_table, limit)
    if not candidates:
        print("Review queue is empty so nothing to review yet")
    record_ids = sorted({record_id for a, b, _, _ in candidates for record_id in (a, b)})
    details = fetch_record_details(conn, record_ids, schema_cols, schema_name, sync_table)
    total = 0
    for record_a, record_b, score, features in candidates:
        print("\n" + "=" * 72)
        print(format_record(record_a, details.get(record_a), schema_cols))
        print(format_record(record_b, details.get(record_b), schema_cols))
        decision = decide(score, features)
        if decision == "quit":
            print("Stopped reviewing records")
            break
        if decision == "skip":
            continue
        active_learning.record_review(conn, record_a, record_b, decision, schema_name, review_table)
        total += 1
        print(f"Recorded review {decision}")
        
    if total:
        classifier = active_learning.maybe_fit(conn, schema_cols, schema_name, review_table)
        if classifier is not None:
            print(f"\nActive learning classifer was trained on {classifier.total_trained} labels. New review candidates will be scored with it now")

    return total

def main():
    parser = argparse.ArgumentParser(description="Review candidate from the database review queue here and give them labels")
    parser.add_argument("--limit", type=int, default=10, help="Number of candidates to review")
    parser.add_argument("--schema-name", default=None, help="Database schema name")
    parser.add_argument("--sync-table", default=None, help="Sync table, the audit table to keep track of records processed")
    parser.add_argument("--review-table", default="identity_review_queue")
    args = parser.parse_args()
    schema_name = args.schema_name or os.environ.get("GRAPH_SYNC_NAME")
    sync_table = args.sync_table or os.environ.get("GRAPH_SYNC_TABLE")
    if not schema_name or sync_table:
        print("Cannot access records details without schema name and name of sync table")
        sys.exit(1)
    schema_cols = load_schema()
    with connect_postgres(PostgresConfig.from_env()) as conn:
        total = record_decisions(conn, schema_cols, schema_name, sync_table, args.review_table, args.limit)
        print(f"\n\nRecorded total of {total} decisions")

if __name__ == "__main__":
    main()