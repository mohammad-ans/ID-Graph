from __future__ import annotations
import unittest
import yaml, hashlib, statistics
import sys
from pathlib import Path


MAIN_DIR = Path(__file__).parent.parent / "main"
DEMO_DIR = Path(__file__).parent.parent / "demo"
sys.path.insert(0, str(MAIN_DIR))
sys.path.insert(0, str(DEMO_DIR))

from graph_model import GraphRow, row_to_ngql, vid, add_identity
from supernode import OnlineStats, shanon_entropy

def load_schema():
    with open(MAIN_DIR / "schema.yaml") as file:
        return yaml.safe_load(file)

def build_row(record_id, email=None, phone=None, transaction_date="2024-01-01T00:00:00", merchant_name="abc", screen_width="1000", screen_length="800", ip_country="us", city="New York", language="en-US"):
    def sha(v):
        return hashlib.sha256(v.strip().lower().encode("utf-8")).hexdigest() if v else None
    
    return {
        "record_id": record_id, "source_table": "orders", "transaction_date": merchant_name, "merchant_url": "https://abc.com", "hashed_email": sha(email),
        "hashed_phone": sha(phone), "maid": None, "screen_width": screen_width, "screen_length": screen_length, "ip_country": ip_country, "city": city, "language": language
    }

def buid_identity(nebula, schema_cols, raw_rows):
    rows = [GraphRow.from_db_row(r, schema_cols) for r in raw_rows]
    for row in rows:
        nebula.execute_many(row_to_ngql(row))
    identifiers = {vid(id_type, val) for row in rows for id_type, val in row if val}
    statements, identity = add_identity(identifiers)
    nebula.execute_many(statements)
    return identity

class OnlineStatsTests(unittest.TestCase):
    def test_statistics(self):
        x_list = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
        stats = OnlineStats()
        for x in x_list:
            stats.update(x)
        self.assertAlmostEqual(stats.mean, statistics.mean(x_list))
        self.assertAlmostEqual(stats.stdev, statistics.stdev(x_list))

    def test_zscore_before_min_population(self):
        stats = OnlineStats()
        stats.update(1.0)
        self.assertEqual(stats.zscore(1000.0), 0.0)

    def test_zscore_no_spread(self):
        stats = OnlineStats()
        for _ in range(5):
            stats.update(3.0)
        self.assertEqual(stats.zscore(1000.0), 0.0)

    def test_zscore_sign(self):
        stats = OnlineStats()
        for x in [8.0, 9.0, 10.0, 11.0, 12.0]:
            stats.update(x)
        high = stats.zscore(100.0)
        low = stats.zscore(-100.0)
        self.assertGreater(high, 0)
        self.assertLess(low, 0)

class EntropyTests(unittest.TestCase):
    def test_empty_single(self):
        self.assertEqual(shanon_entropy([]), 0.0)
        self.assertEqual(shanon_entropy(["a"]), 0.0)

    def test_identical_labels(self):
        self.assertEqual(shanon_entropy(["a", "a", "a"]), 0.0)

    def test_distinct(self):
        self.assertAlmostEqual(shanon_entropy(["a", "b", "c"]), 1.0)

    def test_not_full_distinct(self):
        score = shanon_entropy(["a", "a", "b"])
        self.assertGreater(score, 0.0)
        self.assertLess(score, 1.0)

    def test_none_values(self):
        self.assertEqual(shanon_entropy([None, None]), 0.0)
        self.assertEqual(shanon_entropy(["a", "b", None]), shanon_entropy(["a", "b"]))
