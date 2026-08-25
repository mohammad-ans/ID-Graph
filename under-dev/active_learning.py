import logging
import math
import numpy
from dataclasses import dataclass
import json

logger = logging.getLogger()

FEATURES = ("screen_width", "screen_length", "ip_country", "city", "language", "temporal_same_day", "temporal_same_week", "temporal_same_month", "merchant_name")


def parse_config(schema_cols: dict):
    out = {"active_learning_min_labels": 15}
    for item in schema_cols.get("probabilistic", []):
        out.update(item)
    return out

@dataclass
class LogisticClassifier:
    weights: numpy.ndarray
    bias: float
    total_trained: int

    def predict_prolly(self, features: dict):
        x = numpy.array([1.0 if features.get(name) else 0.0 for name in FEATURES], dtype=float)
        z = float(numpy.dot(self.weights, x) + self.bias)
        z = max(min(z, 35.0), -35.0)
        return 1.0 / (1.0 + math.exp(-z))

def fetch_review_queue(conn, schema_name: str, review_table: str = "identity_review_queue", limit: int = 20):
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT record_id_a, record_id_b, score, features
            FROM {schema_name}.{review_table}
            WHERE decision IS NULL ORDER BY ABS(score - 0.5) ASC
            LIMIT %s
        """, (limit, ))
        return cur.fetchall()

def fetch_labeled(conn, schema_name: str, review_table: str = "identity_review_queue"):
    rows = None
    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT features, decision 
            FROM {schema_name}.{review_table}
            WHERE decision is NOT NULL
        """)
        rows = cur.fetchall()
    labeled = []
    for features_db, decision in rows:
        features = features_db
        if not isinstance(features_db, dict):
            features = json.loads(features_db)
            labeled.append((features, 1 if decision == "match" else 0))
        return labeled
