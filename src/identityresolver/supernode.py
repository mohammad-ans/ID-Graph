from __future__ import annotations
import datetime
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nebula_client import NebulaClient

BURST_WINDOW_SECONDS = 3600
MIN_POPULATION = 3
Z_SINGLE_FEATURE = 3.0
Z_ENSEMBLE = 2.0

FEATURE_NAMES = {"identifier_count", "record_count", "identifier_growth", "signal_diversity", "temporal_burst"}

class OnlineStats:

    def __init__(self):
        self.n = 0
        self.mean = 0.0
        self.m2 = 0.0

    def update(self, x):
        self.n += 1
        delta = x - self.mean
        self.mean += delta / self.n
        delta2 = x - self.mean
        self.m2 += delta * delta2
    @property
    def variance(self):
        if self.n < 2:
            return 0.0
        return self.m2 / (self.n - 1)
    @property
    def stdev(self):
        return math.sqrt(self.variance)

    def zscore(self, x):
        if self.n < 2 or self.stdev == 0:
            return 0.0
        return (x - self.mean) / self.stdev

@dataclass
class ClusterFeatures:
    identity_vid: str
    identifier_count: int
    record_count: int
    identifier_growth: int
    signal_diversity: int
    temporal_burst: int

    def as_dict(self):
        return {name : getattr(self, name) for name in FEATURE_NAMES}


@dataclass
class AnomalyResult:
    features: ClusterFeatures
    z_sources: dict[str, float] = field(default_factory=dict)
    mean_z: float = 0.0
    max_z: float | None = None
    is_anomalous: bool = False
    population_ready: bool = False
    reason: str = ""


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except:
        return None

def shanon_entropy(labels: list[str]):
    labels = [label for label in labels if label is not None]
    n = len(labels)
    if n <= 1:
        return 0.0
    counts = defaultdict(int)
    for label in labels:
        counts[label] += 1
    entropy = -sum((c / n) * math.log2(c / n) for c in counts.values())
    max_possible = math.log2(n)
    return entropy / max_possible if max_possible > 0 else 0.0

def temporal_burst_score(dates: list[datetime.datetime]):
    dates = sorted(d for d in dates if d is not None)
    n = len(dates)
    if n < 2:
        return 0.0
    window = datetime.timedelta(seconds=BURST_WINDOW_SECONDS)
    bursty = 0
    for i, d in enumerate(dates):#fixx
        near_prev = i > 0 and (d - dates[i - 1]) <= window
        near_next = i < n - 1 and (dates[i + 1] - d) <= window
        if near_prev or near_next:
            bursty += 1
    return bursty / n

def fetch_cluster_snapshot(identity_vid: str, nebula: NebulaClient, schema_cols: dict):
    signals = [s["name"] for s in schema_cols["signal_groups"]]
    identifiers = [i["name"] for i in schema_cols["identifiers"] if i["include_in_belongs_to"]]
    identifier_identity_edges = ",".join(f"has_{name}" for name in identifiers)
    signals_query_part = ",".join(f"properties($$).{name} AS {name}" for name in signals)
    result = nebula.execute(
        f'GO FROM "{identity_vid}" OVER belongs_to REVERSELY '
        f'WHERE properties(edge).end_date == "" '
        f"YIELD src(edge) AS identifier_vid "
        f'| GO FROM $-.identifier_vid OVER {identifier_identity_edges} REVERSELY '
        f'YIELD src(edge) AS record_vid, '
        f'$-.identifier_vid AS identifier_vid, '
        f'properties($$).transaction_date AS t_date, '
        f'{signals_query_part}'
    )
    by_record = defaultdict(lambda: {"identifiers": set(), "signals": {}, "t_date": None})
    for i in range(result.row_size()):
        row = [v.cast() for v in result.row_values(i)]
        record_vid = row[0]
        identifier_vid = row[1]
        t_date = row[2]
        rec = by_record[record_vid]
        rec["identifiers"].add(identifier_vid)
        rec["t_date"] = t_date
        offset = 3
        for signal in signals:
            rec["signals"][signal] = row[offset]
            offset += 1
    return by_record

def compute_features(identity_vid: str, snapshot: dict):
    all_identifiers = set()
    signal_tuples = []
    dates = []
    for record in snapshot.values():
        all_identifiers.update(record["identifiers"])
        signal_tuples.append(str(tuple(record["signals"].values())))
        parsed = parse_date(record["t_date"])
        if parsed is not None:
            dates.append(parsed)
    return ClusterFeatures(
        identity_vid=identity_vid,
        identifier_count=len(all_identifiers),
        record_count=len(snapshot),
        identifier_growth=0,
        signal_diversity=shanon_entropy(signal_tuples),
        temporal_burst=temporal_burst_score(dates)
    )


class SupernodeAnomalyScorer:
    def __init__(self, z_single: float = Z_SINGLE_FEATURE, z_ensemble: float = Z_ENSEMBLE, min_population: int = MIN_POPULATION):
        self.stats: dict[str, OnlineStats] = {name: OnlineStats() for name in FEATURE_NAMES}
        self.last_identifier_count: dict[str, int] = {}
        self.history: list[AnomalyResult] = []
        self.z_single = z_single
        self.z_ensemble = z_ensemble
        self.min_population = min_population

    def score(self, identity_vid: str, nebula: NebulaClient, scehma_cols: dict):
        snapshot = fetch_cluster_snapshot(identity_vid, nebula, scehma_cols)
        features = compute_features(identity_vid, snapshot)
        if features.record_count  == 0:
            result = AnomalyResult(features, reason="Identity has zero transactions inserted in graph db, meaning the identifiers linked to it also have zero transactions")
            self.history.append(result)
            return result
        prior_count = self.last_identifier_count.get(identity_vid, 0)
        features.identifier_growth = max(features.identifier_count - prior_count, 0)
        self.last_identifier_count[identity_vid] = features.identifier_count
        values = features.as_dict()
        z_scores = {}
        for name, value in values.items():
            z_scores[name] = self.stats[name].zscore(value)
            self.stats[name].update(value)
        population_ready = self.stats["identifier_count"].n >= self.min_population
        max_z = max(z_scores.values())
        mean_z = sum(max(z, 0.0) for z in z_scores.values()) / len(z_scores)
        is_anomalous = population_ready and (max_z >= self.z_single or mean_z >= self.z_ensemble)
        if not population_ready:
            reason = f"Population not ready, so cannot call anything as outlier. Identifiers count {self.stats['identifier_count'].n} Min population {self.min_population}"
        elif is_anomalous:
            reason = f"Feature with value {max_z:.2f} standard deviates from the population mean_z {mean_z:.2f}"
        else:
            reason = f"Within normal range mean_z {mean_z:.2f} z {max_z:.2f}"
        result = AnomalyResult(features, z_scores, mean_z, max_z, is_anomalous, population_ready, reason)
        self.history.append(result)
        return result
