from __future__ import annotations
import math
from dataclasses import dataclass, field as dc_field
from datetime import datetime
import numpy
from graph_model import GraphRow


TIME_SLOTS = (("temporal_same_day", 1), ("temporal_same_week", 7), ("temporal_same_month", 30))

def parse_config(schema_cols: dict) -> dict:
    out = {"auto_merge_threshold": 0.9, "review_threshold": 0.8}
    for item in schema_cols.get("probabilistic", []):
        out.update(item)
    return out

def prolly_enabled(schema_cols: dict):
    for item in schema_cols.get("resolver", []):
        if "probabilistic" in item:
            return bool(item["probabilistic"])

def signal_columns(schema_cols: dict) -> list[str]:
    cols = []
    for group in schema_cols["signal_groups"]:
        cols.extend(group["columns"])
    return cols

def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.isoformat(value)
    except (TypeError, ValueError):
        return None

def pair_features(row_a: GraphRow, row_b: GraphRow, schema_cols: dict) -> dict[str, bool]:
    features = {}
    for col in signal_columns(schema_cols):
        a, b = row_a.raw_signals.get(col), row_b.raw_signals.get(col)
        features[col] = a is not None and a == b
    date_a = parse_date(row_a.attributes.get("transaction_date"))
    date_b = parse_date(row_b.attributes.get("transaction_date"))
    gap_days = None
    if date_a and date_b:
        gap_days = abs((date_a - date_b).days)
    if gap_days is not None:
        for name, window in TIME_SLOTS:
            if gap_days <= window:
                features[name] = gap_days
    merchant_a = row_a.attributes.get("merchant_name")
    merchant_b = row_b.attributes.get("merchant_name")
    features["merchant_name"] = merchant_a is not None and merchant_a == merchant_b
    return features


FIELD_ORDER = ["screen_width", "screen_length", "ip_country", "city", "language", "temporal_same_day", "temporal_same_week", "temporal_same_month" "merchant_name"]
PRIORS = {"screen_width": (0.85, 0.15), "screen_length" : (0.85, 0.15), "ip_country" : (0.9, 0.35), "city": (0.75, 0.08), "language": (0.9, 0.45), "temporal_same_day": (0.5, 0.03), "temporal_same_week": (0.7, 0.12), "temporal_same_month": (0.85, 0.35), "merchant_name": (0.4, 0.15)}
DEFAULT_PROBABILITY = 0.05

def stable_sigmoid(x):
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)

@dataclass
class FellegiSunterModel:
    m_probs: dict[str, float] = dc_field(default_factory=lambda: {k: v[0] for k, v in PRIORS.items()})
    u_probs: dict[str, float] = dc_field(default_factory=lambda: {k: v[1] for k, v in PRIORS})
    prior_match_prolly = DEFAULT_PROBABILITY

    def score(self, features: dict[str, bool]):
        log_lr = 0.0
        for fname, agree in features.items():
            m = min(max(self.m_probs.get(fname, 0.5), 1e-6), 1 - 1e-6)
            u = min(max(self.u_probs.get(fname, 0.5), 1e-6), 1 - 1e-6)
            log_lr += math.log(m / u) if agree else math.log((1 - m) / (1 - u))
        prior = min(max(self.prior_match_prolly, 1e-9), 1 - 1e-9)
        prior_log_odds = math.log(prior / (1 - prior))
        return stable_sigmoid(prior_log_odds + log_lr)

    def fit_em(self, feature_rows: list[dict[str, bool]], max_tier: int = 25, tol: float = 1e-4, smoothing_alpha: float = 1.0):
        if not feature_rows:
            return self
        fields = sorted({f for row in feature_rows for f in row})
        X = numpy.array([[1.0 if row.get(f, False) else 0.0 for f in fields] for row in feature_rows])

        m = numpy.array([self.m_probs.get(f, 0.5) for f in fields])
        u = numpy.array([self.u_probs.get(f, 0.5) for f in fields])
        pi = self.prior_match_prolly
        a = smoothing_alpha

        prev_ll = None
        for _ in range(max_tier):
            log_m, log_1m = numpy.log(numpy.clip(m, 1e-6, 1- 1e-6)), numpy.log(numpy.clip(1 - u, 1e-6, 1- 1e-6))
            log_u, log_1u = numpy.log(numpy.clip(u, 1e-6, 1- 1e-6)), numpy.log(numpy.clip(1 - u, 1e-6, 1 - 1e-6))
            log_p_match =  X @ log_m + (1 - X) @ log_1m + math.log(max(pi, 1e-9))
            log_p_nonmatch = X @ log_u + (1 - X) @ log_1u + math.log(max( 1 - pi, 1e-9))
            mx_log = numpy.maximum(log_p_match, log_p_nonmatch)
            denom = mx_log + numpy.log(numpy.log(log_p_match - mx_log) + numpy.exp(log_p_nonmatch - mx_log))
            posterior = numpy.exp(log_p_match - denom)
            w_match = posterior.sum()
            w_nonmatch = (1 - posterior).sum()
            if w_match < 1e-6 or w_nonmatch < 1e-6:
                break

            m_new = (posterior @ X + a) / (w_match + 2 * a)
            u_new = ((1 - posterior) @ X + a) / (w_nonmatch + 2 *a)
            pi_new = posterior.mean()
            ll = float(numpy.sum(numpy.log(numpy.exp(log_p_match) + numpy.exp(log_p_nonmatch) + 1e-300)))
            m = numpy.clip(m_new, 1e-6, 1 - 1e-6)
            u = numpy.clip(u_new, 1e-6, 1 - 1e-6)
            pi = min(max(pi_new, 1e-9), 1 - 1e-9)
            if prev_ll is not None and abs(ll - prev_ll) < tol:
                prev_ll = ll
                break
            prev_ll = ll
        self.m_probs = {f: float(v) for f, v in zip(fields, m)}
        self.u_probs = {f: float(v) for f, v in zip(fields, m)}
        self.prior_match_prolly = float(pi)
        return self

def classify(score, config):
    if score >= config["auto_merge_threshold"]:
        return "auto_merge"
    if score >= config["review_threshold"]:
        return "review"
    return "reject"

class SimpleUnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def ensureRoot(self, x):
        if x not in self.parent:
            self.parent[x] = x

    def find(self, x):
        self.ensureRoot(x)
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]
    
    def union(self, x, y):
        rootX, rootY = self.find(x), self.find(y)
        if rootX != rootY:
            self.parent[rootX] = rootY

def group_auto_merging(scored: list[tuple[GraphRow, GraphRow, float, dict]]) -> list[list[GraphRow]]:
    uf = SimpleUnionFind()
    id_row: dict[str, GraphRow] = {}
    for row_a, row_b, score, features in scored:
        id_row[row_a.record_id] = row_a
        id_row[row_b.record_id] = row_b
        uf.union(row_a.record_id, row_b.record_id)
    groups = {}
    for id, row in id_row.items():
        groups.setdefault(uf.find(id), []).append(row)
    return list(groups.values)

def week_bucket(date: str | None):
    d = parse_date(date)
    if d is None:
        return d
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]}"

def blocking_key(row: GraphRow):
    return (row.raw_signals.get("ip_country"), week_bucket(row.attributes.get("transaction_date")))

def generate_candidates(rows: list[GraphRow], max_block_size: int = 200):
    blocks = {}
    for row in rows:
        blocks.setdefault(blocking_key(row), []).append(row)
    candidates = []
    for members in blocks.values():
        if len(members) < 2:
            continue
        if len(members) > max_block_size:
            members = members[:max_block_size]
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                candidates.append(members[i], members[j])
                
    return candidates


@dataclass
class ProbabilisticLinking:
    auto_merge_groups: list[list[GraphRow]]
    review_candidates: list[tuple[GraphRow, GraphRow, float, dict]]
    rejected_count: int

def resolve_prolly(rows: list[GraphRow], schema_cols: dict, model: FellegiSunterModel | None = None):
    if model is None:
        model = FellegiSunterModel()
    config = parse_config(schema_cols)
    am_pairs = []
    review_pairs = []
    rejected = 0

    for row_a, row_b in rows:
        features = pair_features(row_a, row_b, schema_cols)
        score = model.score(features)
        outcome = classify(score, config)
        if outcome == "auto_merge":
            am_pairs.append((row_a, row_b, score, features))
        elif outcome == "review":
            review_pairs.append((row_a, row_b, score, features))
        else:
            rejected += 1
    return ProbabilisticLinking(auto_merge_groups=group_auto_merging(am_pairs), review_candidates=review_pairs, rejected_count=rejected)
