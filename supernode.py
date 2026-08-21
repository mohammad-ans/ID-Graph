from __future__ import annotations
import datetime
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nebula_client import NebulaClient

MIN_POPULATION = 3
BURST_WINDOW_SECONDS = 3600
Z_SINGLE_FEATURE = 3.0

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