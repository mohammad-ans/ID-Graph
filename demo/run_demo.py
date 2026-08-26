from __future__ import annotations
import argparse
import logging
import sys
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent / "main"
DEMO_DIR = Path(__file__).resolve().parent
DEV_DIR = Path(__file__).resolve().parent.parent / "under_dev"
sys.path.insert(0, str(MAIN_DIR))
sys.path.insert(0, str(DEMO_DIR))
sys.path.insert(0, str(DEV_DIR))

import yaml
from nebula_f import FakeNebulaClient
from dummy_data import build_batches, build_showcase_rows, make_rows, SCHEMA_COLS
import active_learning as al
from graph_model import GraphRow, belongs_to_identity,  add_probable_identity, vid as graph_vid, row_to_ngql, add_identity
from batch_id_union import cluster_identifiers, distinct_identifiers
from sync_audience_graph import fetch_identities, write_batch, write_identity_queries
from probability import prolly_enabled, resolve_prolly,  pair_features, FellegiSunterModel
from supernode import SupernodeAnomalyScorer
from fake_pg import Cursor, ReviewQueue


RECORD_LABELS = {
    "r-alice-1": "Alice", "r-alice-2": "Alice", "r-dave-1": "Dave",  "r-dave-2": "Dave", "r-bob-1": "Bob", "r-carol-1": "Carol",
    "r-promo-1": "Person1 (promo)", "r-promo-2": "Person2 (promo)", "r-promo-3": "Person3 (promo)", "r-promo-4": "Person4 (promo)", "r-promo-5": "Person5 (promo)", "r-promo-6": "Person6 (promo)", "r-promo-7": "Person7 (promo)", 
    "r-erin-1": "Erin", "r-erin-2": "Erin", "r-travel-1": "Traveler-A", "r-travel-2": "Traveler-B", "r-lonewolf-1": "LoneWolf"
}

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

def run_batch(nebula, schema_cols, raw_rows, static_invalid, max_identifiers, remap_type, phone_gap, prob_model=None, scorer=None):
    rows = [GraphRow.from_db_row(r, schema_cols) for r in raw_rows]
    clustered, transaction_dates, unresolvable = cluster_identifiers(rows, static_invalid, phone_gap, schema_cols)
    all_identifiers = distinct_identifiers(clustered)
    identifier_identity_map = fetch_identities(all_identifiers, nebula, 2)
    if not phone_gap:
        transaction_dates = None
    statements, invalid_identifiers_declare, db_statements = belongs_to_identity(identifier_identity_map, clustered, transaction_dates, max_identifiers, remap_type, schema_cols, nebula, scorer)
    prob_result = None
    if unresolvable and prolly_enabled(schema_cols):
        prob_result = resolve_prolly(unresolvable, schema_cols, prob_model)
        for group_rows, score in prob_result.auto_merge_groups:
            group_statements, _ = add_probable_identity(group_rows, score)
            statements.extend(group_statements)
    # for row in statements:
    #     print(row)
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
            identifier = primary_identifier_vid(row)
            if identifier is not None:
                self.record_to_identity[row.record_id] = current_active_identity(self.graph, identifier)
                self.record_to_identifier[row.record_id] = identifier
                self.record_kind[row.record_id] = "identifier"
                continue
            probable = current_probable_match_identity(self.graph, row.vertex_id)
            if probable is not None:
                self.record_to_identity[row.record_id] = probable
                self.record_to_identifier[row.record_id] = row.record_id
                self.record_kind[row.record_id] = "probable_match"
        for record_id, identifier in self.record_to_identifier.items():
            if identifier is None:
                continue
            if record_id in [r.record_id for r in rows] or self.record_kind.get(record_id) == "probable_match" or record_id in self.frozen:
                continue

            current = current_active_identity(self.graph, identifier)
            if current is None or current == self.record_to_identity[record_id]:
                continue
            if identifier in new_identifiers:
                self.frozen.add(record_id)
                continue
            self.record_to_identity[record_id] = current

    def roster(self):
        out = {}
        for record_id, identity_vid in self.record_to_identity.items():
            if identity_vid is None:
                continue
            out.setdefault(identity_vid, []).append(RECORD_LABELS.get(record_id, record_id))
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

def group_rows(rows: list[dict]):
    groups = {}
    for row in rows:
        record_id = row["record_id"]
        key = "showcase_promo" if "promo" in record_id else record_id.split("-")[1]
        groups.setdefault(key, []).append(row)
    return groups

SHOWCASE_ORDER = ["nadia", "omar", "priya", "quinn", "rosa", "sam", "showcase_promo"]

def supernode_demo(max_identifiers_hint: int):
    print("\n" + "=" * 72)
    print("Super node detection showcase like its adaptivity unlike static n before")
    print("6 ordinary customers and 1 shared promo email supernode-shaped cluster")
    schema_cols = load_schema_cols()
    nebula = FakeNebulaClient()
    scorer = SupernodeAnomalyScorer()
    groups = group_rows(build_showcase_rows())
    identity_vids = {}
    for key, raw_rows in groups.items():
        identifiers = set()
        rows = [GraphRow.from_db_row(row, schema_cols) for row in raw_rows]
        for row in rows:
            nebula.execute_many(row_to_ngql(row))
            identifiers.update(graph_vid(id_type, value) for id_type, value in row.identifiers.items() if value)
        statements, identity = add_identity(identifiers)
        nebula.execute_many(statements)
        identity_vids[key] = identity
    header = f"{'identity':<24}{'idc':>5}{'recs':>6}{'growth':>8}{'diversity':>11}{'burst':>8}{'mean_z':>9}{'max_z':>8}  verdict"
    print(header,"-" * len(header), sep="\n")
    for key in SHOWCASE_ORDER:
        label = key.capitalize()
        if key == "showcase_promo":
            label = "Shared promo supernode"
        result = scorer.score(identity_vids[key], nebula, schema_cols)
        f = result.features
        verdict = "ANOMALOUS" if result.is_anomalous else ("warming up" if not result.population_ready else "normal")
        print(f"{label:<24}{f.identifier_count:>5}{f.record_count:>6}{f.identifier_growth:>8}{f.signal_diversity:>11.2f}{f.temporal_burst:>8.2f}{result.mean_z:>9.2f}{result.max_z:>8.2f}  {verdict}")

    promo_result = scorer.history[-1]
    by_static = promo_result.features.identifier_count > max_identifiers_hint
    if by_static:
        print(f"Promo result could also be caught by static {max_identifiers_hint} max identifiers count. Total identifiers count: {promo_result.features.identifier_count}. The adaptive detector confirms it.")
    else:
        print(f"Promo result could not have been caught by static {max_identifiers_hint} max identifiers count. Total identifiers count: {promo_result.features.identifier_count}. The adaptive detector catches it as: {promo_result.reason}")

DECISIONS = [
    ("match-1a", "match-1b", "match"),
    ("match-2a", "match-2b", "match"),
    ("match-3a", "match-3b", "match"),
    ("match-4a", "match-4b", "match"),
    ("match-5a", "match-5b", "match"),
    ("nonmatch-1a", "nonmatch-1b", "not_match"),
    ("nonmatch-2a", "nonmatch-2b", "not_match"),
    ("nonmatch-3a", "nonmatch-3b", "not_match"),
    ("nonmatch-4a", "nonmatch-4b", "not_match"),
    ("nonmatch-5a", "nonmatch-5b", "not_match"),
    ("borderline-a", "borderline-b", None)
]

def main():
    parser = argparse.ArgumentParser(description="Run demo of the identity graph")
    parser.add_argument("--max-identifiers", type=int, default=3)
    parser.add_argument("--remap-type", type=int, default=3)
    parser.add_argument("--adaptive-detection", action="store_true")
    args = parser.parse_args()
    logging.getLogger().setLevel(logging.WARNING)
    schema_cols = load_schema_cols()
    batches = build_batches()
    nebula = FakeNebulaClient(schema_path=str(MAIN_DIR / "schema.ngql"))

    print("=" * 72)
    print("RampID-style identity graph -- live demo (in-memory styled Nebula)")
    print(f"max_identifiers={args.max_identifiers}  remap_type={args.remap_type}  phone_gap=one")
    print("=" * 72)
    static_invalid: dict[str, set[str]] = {}
    tracker = IdentityTracker(nebula.graph)
    scorer = SupernodeAnomalyScorer() if args.adaptive_detection else None
    all_review_candidates = []

    for i, batch in enumerate(batches, start=1):
        print(f"\n Batch {i}: {len(batch)} incoming rows \n")
        result = run_batch(nebula, schema_cols, batch, static_invalid, args.max_identifiers, args.remap_type, phone_gap=True, scorer=scorer)
        print(f"Batch clusters: {result['clusters']}\n")
        if result["invalid_declared"]:
            invalid_identifiers = pairs_to_static_invalid(result["invalid_declared"])
            for id_type, values in invalid_identifiers.items():
                static_invalid.setdefault(id_type, set()).update(values)
            print(f"Invalid identifiers in current batch: {sum(len(v) for v in invalid_identifiers.values())}")
        else:
            print("No invalid identifiers in this batch")

        if result["unresolvable_count"]:
            prob_result = result["prob_result"]
            print(f"\n{result['unresolvable_count']} could not be resolved deterministicly\n")
            if prob_result is None:
                print(" Probability resolver is off in the schema yaml file\n")
            else:
                merged_count = sum(len(rows) for rows, _ in prob_result.auto_merge_groups)
                print(f"{len(prob_result.auto_merge_groups)} groups of {merged_count} records with help of probability linking on linking signals\n")
                print(f"{len(prob_result.review_candidates)} review queue merges. They are done by humans\n")
                print(f"{prob_result.rejected_count} records were scored low below the thresholds\n")
                all_review_candidates.extend(prob_result.review_candidates)
        tracker.observe_batch(result["rows"], result["all_identifiers"])
        print(f" active identifiers processed total: {len(tracker.roster())}\n")

    print("\n" + "=" * 72)
    print("Final resolved identities: \n")
    roster = tracker.roster()
    for vid in sorted(roster, key=lambda v: (-len(roster[v]), roster[v])):
        print(f" {vid[:24]:24s} {', '.join(roster[vid]) if roster[vid] else 'No active identifiers'}\n")

    orphans = tracker.orphaned_records()
    if orphans:
        print("orphaned records that lost their identities: \n")
        for id in orphans:
            print(f" {id} was under {tracker.record_to_identity[id][:24]}\n")
    if all_review_candidates:
        print("\n\n\n Pending human review identifiers:\n")
        for row_a, row_b, score, features in all_review_candidates:
            agreeing = sorted(k for  k, v in features.items() if v)
            label_a = RECORD_LABELS.get(row_a.record_id, row_a.record_id)
            label_b = RECORD_LABELS.get(row_b.record_id, row_b.record_id)
            print(f" {label_a} and {label_b}: score={score:.3f} agree on {agreeing}\n")

    #scenario proving using AI's testcase to validate system
    print("\n" + "=" * 72)
    print("What to look for\n\n\n")

    bob_id = next((v for v, person in roster.items() if person == ["Bob"]), None)
    carol_id = next((v for v, person in roster.items() if person == ["Carol"]), None)
    dave_id = next((v for v, person in roster.items() if set(person) == {"Dave"}), None)
    promo_people = [v for v, person in roster.items() if any("promo" in x for x in person)]

    if bob_id and carol_id and bob_id != carol_id:
        print("Bob and carol got separate identities, they share the same number but there phone gap is large 1247 days surpassing the limit here. Correct\n")
    else:
        print("Bob and carol have same identity so the phone gap was not honored by the system")
    if dave_id and set(roster.get(dave_id, [])) == {"Dave"}:
        print("Dave's two order 30 days apart merged into same identity as he used same phone")
    else:
        print("Dave'orders were not assigned same identity so the resolution graph is wrong")
    promo_sizes = sorted((len(roster[v]) for v in promo_people), reverse=True)
    if len(promo_sizes) >= 4:
        print(f"The promo email shared by many people was treated as super node and split into {len(promo_people)}. Correct")
    else:
        print(f"Super node currenty split to {len(promo_people)} so remediation might still be going on the batch")
    eren_id = next((v for v, p in roster.items() if set(p) == {"Erin"}), None)
    reviewed_pairs = {frozenset([a.record_id, b.record_id]) for a,b, _,_ in all_review_candidates}
    traveler_reviewed = frozenset(["r-travel-1", "r-travel-2"]) in reviewed_pairs
    lonewolf_untouched = "r-lonewolf-1" not in tracker.record_to_identity

    if eren_id and traveler_reviewed and lonewolf_untouched:
        print("Records with zero identifiers, so no deterministic. Eren's transactions were auto merged by signals, traveler landed in review queue due to different ip. Lonewolf was separate not touching anything so correct")
    else:
        print("Probabilistic linking thresholds were wrongly tweaked or it itself is wrong")

    if scorer is not None:
        print("\n" + "=" * 72)
        print("Super Node class activity during the scenario:\n")
        if scorer.history:
            for r in scorer.history:
                print(f" {r.features.identity_vid[:24]:24s} {r.reason}")
        else:
            print("Nothing scored meaning every identity created was brand new in its batch")
        supernode_demo(max_identifiers_hint=max(args.max_identifiers, 10))

    print("=" * 72)
    print("Active learning using review queue")
    print("=" * 72)
    model = FellegiSunterModel()
    conn = ReviewQueue()
    rows = make_rows()
    print("Score every candidate pair with Fellegi Sunter")
    for a, b, _ in DECISIONS:
        features = pair_features(rows[a], rows[b], schema_cols)
        score = model.score(features)
        conn.insert_candidate(a, b, score, features)
        print(f" {a:<14} / {b:<14} score={score:.4f}")
    print("Fetching the review queue ordered in ascending way on basis of abs(score - 0.5)")
    for record_a, record_b, score, features in al.fetch_review_queue(conn, "public", limit=10):
        print(f" abs(score - 0.5) = {abs(score - 0.5):.4f} score={score:.4f} {record_a} / {record_b}")
    print("\nNow showing the decisions that are pre defined for the demo run")
    for a, b, decision in DECISIONS:
        if decision is None:
            continue
        al.record_review(conn, a, b, decision, "public")
        print(f" recorded for {a} and {b}: {decision}")

    classifier = al.maybe_fit(conn, SCHEMA_COLS, "public")
    if classifier is None:
        print("Not enough labels for match and non match")
    else:
        print(f"Active learning training done on {classifier.total_trained} labels. Coefficients are")
        for name, weight in sorted(classifier.coefficients().items(), key=lambda kv: -abs(kv[1])):
            print(f" {name:<22} {weight:+.3f}")

        print("\nScoring the still undecided bordeline pair now")
        features = pair_features(rows["borderline-a"], rows["borderline-b"], SCHEMA_COLS)
        fellegi_score = model.score(features)
        score, method = al.score(features, model, classifier)
        print(f" If using the Fellegi Sunter, score is {fellegi_score:.4f} ")
        print(f" If using the active learning, score is {score:.4f} with method={method}")
        print(f"\nUncertainity ordered queue after decisions")
        remaining = al.fetch_review_queue(conn, "public", limit=10)
        for record_a, record_b, score, _ in remaining:
            print(f" abs(score - 0.5) = {abs(score - 0.5):.4f} score = {score:.4f} {record_a} / {record_b}")

        if not remaining:
            print("Queue is empty")

if __name__ == "__main__":
    main()
            