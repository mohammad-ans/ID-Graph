from __future__ import annotations
import datetime
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nebula_client import NebulaClient

BURST_WINDOW_SECONDS = 3600

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
        self.m2 = delta * delta2
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
    entropy = sum((c / n) * math.log2(c / n) for c in counts.values())
    max_possible = math.log2(n)
    return entropy / max_possible if max_possible > 0 else 0.0

def temporal_burst_score(dates: list[datetime.datetime]):
    dates = sorted(d for d in dates if d is not None)
    n = len(dates)
    if n < 2:
        return 0.0
    window = datetime.timedelta(seconds=BURST_WINDOW_SECONDS)
    bursty = 0
    for i, d in enumerate(dates):
        near_prev = i > 0 and (d - dates[i - 1])
        near_next = i < n - 1 and (dates[i + 1] - d)
        if near_prev <= window or near_next <= window:
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

def coompute_features(identity_vid: str, snapshot: dict):
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