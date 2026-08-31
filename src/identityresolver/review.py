from __future__ import annotations

import logging
from typing import Callable

from . import active_learning
from .schema import record_id_column, signal_columns

logger = logging.getLogger(__name__)

__all__ = ["review_candidates", "display_columns", "format_record", "prompt_decision"]


def display_columns(schema_cols: dict) -> list[str]:
    """Columns worth showing a reviewer when they compare two records."""
    return list(schema_cols.get("passthrough", []) or []) + signal_columns(schema_cols)


def fetch_record_details(
    conn, record_ids: list[str], schema_cols: dict, schema_name: str, source_table: str
) -> dict[str, dict]:
    if not record_ids:
        return {}
    id_column = record_id_column(schema_cols)
    columns = [id_column] + display_columns(schema_cols)
    quoted = ", ".join(f'"{column}"' for column in columns)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {quoted} FROM {schema_name}.{source_table} WHERE {id_column} = ANY(%s)",
            (record_ids,),
        )
        rows = cur.fetchall()
    return {row[0]: dict(zip(columns, row)) for row in rows}


def format_record(record_id: str, details: dict | None, schema_cols: dict) -> str:
    if details is None:
        return f"  {record_id}: no details found for this record"
    fields = " ".join(f"{c}={details.get(c)!r}" for c in display_columns(schema_cols))
    return f"  {record_id} {fields}"


def prompt_decision(score: float, features: dict) -> str:
    """Ask a terminal user to judge one pair. Returns match/not_match/skip/quit."""
    print(f"\nscore={score:.4f} agreement features={features}")
    while True:
        choice = input(" match / not match / skip / quit > ").strip().lower()
        if choice in {"m", "match"}:
            return "match"
        if choice in {"n", "not match", "not_match"}:
            return "not_match"
        if choice in {"s", "skip"}:
            return "skip"
        if choice in {"q", "quit"}:
            return "quit"
        print("Valid choices: m/match, n/not match, s/skip, q/quit")


def review_candidates(conn, schema_cols: dict, schema_name: str, source_table: str, review_table: str = "identity_review_queue", limit: int = 10, decider: Callable[[float, dict], str] = prompt_decision, output: Callable[[str], None] = print,) -> int:
    candidates = active_learning.fetch_review_queue(conn, schema_name, review_table, limit)
    if not candidates:
        output("Review queue is empty, nothing to review yet")
        return 0

    record_ids = sorted({rid for a, b, _, _ in candidates for rid in (a, b)})
    details = fetch_record_details(conn, record_ids, schema_cols, schema_name, source_table)

    total = 0
    for record_a, record_b, score, features in candidates:
        output("\n" + "=" * 72)
        output(format_record(record_a, details.get(record_a), schema_cols))
        output(format_record(record_b, details.get(record_b), schema_cols))
        decision = decider(score, features)
        if decision == "quit":
            output("Stopped reviewing")
            break
        if decision == "skip":
            continue
        active_learning.record_review(
            conn, record_a, record_b, decision, schema_name, review_table
        )
        total += 1
        output(f"Recorded review: {decision}")

    if total:
        classifier = active_learning.maybe_fit(conn, schema_cols, schema_name, review_table)
        if classifier is not None:
            output(
                f"\nActive learning classifier trained on {classifier.total_trained} labels. "
                "New review candidates will be scored with it."
            )
    return total
