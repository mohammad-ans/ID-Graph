from __future__ import annotations
import sys
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent / "core"
DEMO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MAIN_DIR))
sys.path.insert(0, str(DEMO_DIR))

import yaml
from main.graph_model import GraphRow, row_to_ngql, belongs_to_identity, add_probable_identity
from main.batch_id_union import cluster_identifiers, distinct_identifiers
from main.sync_audience_graph import fetch_identities, write_batch, write_identity_queries
from main.probability import prolly_enabled, resolve_prolly

def load_schema_cols():
    with open(MAIN_DIR / "schema.yaml") as f:
        return yaml.safe_load(f)

def build_cols_list(schema_cols: dict):
    cols = list(schema_cols["passthrough"])
    cols.extend(el["column"] for el in schema_cols["identifiers"])
    for group in schema_cols["signal_groups"]:
        cols.extend(group["columns"])
    cols.append(schema_cols["record_id"][0])
    return cols

def pairs_to_static_invalid(pairs: list[list[str]]):
    out = {}
    for id_type, value in pairs:
        out.setdefault(id_type, set()).add(value)
    return out

def run_batch(nebula, schema_cols, raw_rows, static_invalid, max_identifiers, remap_type, phone_gap, prob_model=None):
    rows = [GraphRow.from_db_row(r, schema_cols) for r in raw_rows]
    clustered, transaction_dates, unresolvable = cluster_identifiers(rows, static_invalid, phone_gap, schema_cols)
    all_identifiers = distinct_identifiers(clustered)
    identifier_identity_map = fetch_identities(all_identifiers, nebula, 2)
    if not phone_gap:
        transaction_dates = None
    statements, invalid_identifiers_declare, db_statements = belongs_to_identity(identifier_identity_map, clustered, transaction_dates, max_identifiers, remap_type, schema_cols, nebula)
    prob_result = None
    if unresolvable and prolly_enabled(schema_cols):
        prob_result = resolve_prolly(unresolvable, schema_cols, prob_model)
        for group_rows, score in prob_result.auto_merge_groups:
            group_statements, _ = add_probable_identity(group_rows, score)
            statements.extend(group_statements)
    write_batch(nebula, rows, max_workers=2)
    write_identity_queries(nebula, statements)
    print(f"{len(rows)} record written, {len(statements)} identity-graph statements")
    return {
        "clusters": len(clustered),
        "unresolvable_count": len(unresolvable),
        "prob_result": prob_result,
        "invalid_declared": invalid_identifiers_declare,
        "rows": rows,
        "all_identifiers": set(all_identifiers)
    }

def primary_identifier_vid(row: GraphRow):
    if row.identifiers.get("phone"):
        return f"phone:{row.identifiers['phone']}"
    if row.identifiers.get("email"):
        return f"email:{row.identifiers['email']}"
    return None

def current_active_identity(graph, identifier_vid: str):
    for identity_vid, props in graph.out_edges.get(identifier_vid, {}).get("belongs_to", {}).items():
        if props.get("end_date", "") == "":
            return identity_vid
    return None

def current_probable_match_identity(graph, record_vid: str):
    edges = graph.out_edges.get(record_vid, {}).get("probable_match", {})
    if not edges:
        return None
    return next(iter(edges))

class IdentityTracker:
    def __init__(self, graph):
        self.graph = graph
        self.record_to_identity: dict[str, str] = {}
        self.record_to_identifier: dict[str, str] = {}
        self.record_kind: dict[str, str] = {}
        self.frozen: set[str] = set()

    def observe_batch(self, rows: list[GraphRow], new_identifiers: set[str]):
        for row in rows:
            identity = primary_identifier_vid(row)
            if identity is not None:
                self.record_to_identity[row.record_id] = identity
                self.record_to_identifier[row.record_id] = current_active_identity(self.graph, identity)
                self.record_kind[row.record_id] = "identifier"
                continue
            probable = current_probable_match_identity(self.graph, row.vertex_id)
            if probable is not None:
                self.record_to_identity[row.record_id] = probable
                self.record_to_identifier[row.record_id] = row.record_id
                self.record_kind[row.record_id] = "probable_match"
        for record_id, identity in self.record_to_identifier.items():
            if record_id in [r.record_id for r in rows] or self.record_kind.get(record_id) == "probable_match" or record_id in self.frozen:
                continue

            current = current_active_identity(self.graph, identity)
            if current is None or current == self.record_to_identity[record_id]:
                continue
            if identity in new_identifiers:
                self.frozen.add(record_id)
                continue
            self.record_to_identity[record_id] = current

    def roster(self):
        out = {}
        for record_id, identity_vid in self.record_to_identity.items():
            if identity_vid is None:
                continue
            out.setdefault(identity_vid, []).append(record_id)
        return {k: sorted(v) for k, v in out.items()}

    def orphaned_records(self):
        orphaned = []
        for record_id, identity in self.record_to_identifier.items():
            if self.record_kind.get(record_id) == "probable_match":
                continue
            current = current_active_identity(self.graph, identity)
            stored = self.record_to_identity[record_id]
            if current != stored:
                orphaned.append(record_id)
        return orphaned
            