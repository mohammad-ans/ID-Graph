import logging
import math
import numpy
from dataclasses import dataclass
import json

logger = logging.getLogger()

FEATURES = ("screen_width", "screen_length", "ip_country", "city", "language", "temporal_same_day", "temporal_same_week", "temporal_same_month", "merchant_name")


def parse_config(schema_cols: dict):
    out = schema_cols.get("probabilistic")
    for el in out:
        if "active_learning_min_labels" in el.keys():
            return el

def features_arr(features):
    return numpy.array([1.0 if features.get(name) else 0.0 for name in FEATURES], dtype=float)

@dataclass
class LogisticClassifier:
    weights: numpy.ndarray
    bias: float
    total_trained: int

    def predict_prolly(self, features: dict):
        x = features_arr(features)
        z = float(numpy.dot(self.weights, x) + self.bias)
        z = max(min(z, 35.0), -35.0)
        return 1.0 / (1.0 + math.exp(-z))
    
    def coefficients(self):
        return dict(zip(FEATURES, (float(w) for w in self.weights)))

def logistic_regression(labeled: list[tuple[dict, int]], l2: float = 1.0, learning_rate: float = 0.3, iterations: int = 800):
    if not labeled:
        raise ValueError("Logistic regression got nothing labelled to start fitting or learning")
    x = numpy.stack([features_arr(features) for features, _ in labeled])
    y = numpy.array([label for _, label in labeled], dtype=float)
    n, d = x.shape
    weights = numpy.zeros(d)
    bias = 0.0
    for _ in range(iterations):
        z = numpy.clip(x @ weights + bias, -35.0, 35.0)
        preds = 1.0 / (1.0 + numpy.exp(-z))
        error = preds - y
        grad_w = (x.T @ error) / n + (l2 / n) * weights
        grad_b = float(numpy.mean(error))
        weights -= learning_rate * grad_w
        bias -= learning_rate * grad_b
    return LogisticClassifier(weights=weights, bias=bias, total_trained=len(labeled))

def score(features: dict, fs_model, classifier: LogisticClassifier | None):
    if classifier is not None:
        return classifier.predict_prolly(features), "learned_classifier"
    return fs_model.score(features), "fellegi_sunter"

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
            WHERE decision IS NOT NULL
        """)
        rows = cur.fetchall()
    labeled = []
    for features_db, decision in rows:
        features = features_db
        if not isinstance(features_db, dict):
            features = json.loads(features_db)
        labeled.append((features, 1 if decision == "match" else 0))
    return labeled

def maybe_fit(conn, schema_cols: dict, schema_name: str, review_table: str = "identity_review_queue"):
    config = parse_config(schema_cols)
    min_labels = config["active_learning_min_labels"]
    labeled = fetch_labeled(conn, schema_name, review_table)
    matches = [pair for pair in labeled if pair[1] == 1]
    non_match = [pair for pair in labeled if pair[1] == 0]
    if len(matches) < min_labels or len(non_match) < min_labels:
        logger.info(f"For active learning, {min_labels} are required but curr given are matched: {len(matches)} and non-matched: {len(non_match)}")
        return None
    classifier = logistic_regression(labeled)
    logger.info(f"Fitted classifiers in {len(labeled)} labels {len(matches)} match / {len(non_match)} non match")
    return classifier

def record_review(conn, record_a, record_b, decision: str, schema_name: str, review_table: str = "identity_review_queue"):
    if decision not in ("match", "not_match"):
        raise ValueError(f"decision must be match or not_match, got {decision!r}")
    with conn.cursor() as cur:
        cur.execute(f"""
            UPDATE {schema_name}.{review_table}
            SET decision = %s, decided_at = now() 
            WHERE (record_id_a = %s AND record_id_b = %s) OR (record_id_a = %s AND record_id_b = %s)
        """, (decision, record_a, record_b, record_b, record_a))
        updated = cur.rowcount
    conn.commit()
    if updated == 0:
        logger.info(f"no row matched ({record_a}, {record_b}) in {schema_name}.{review_table}")
    return updated