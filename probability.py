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