from __future__ import annotations
import unittest
import yaml, hashlib, statistics, datetime
import sys, importlib
from pathlib import Path

import identityresolver.presets


PRESETS = Path(next(iter(identityresolver.presets.__path__)))
DEMO_DIR = Path(__file__).parent.parent / "demo"
sys.path.insert(0, str(DEMO_DIR))

from identityresolver.graph_model import GraphRow, row_to_ngql, vid, add_identity
from identityresolver.supernode import OnlineStats, shanon_entropy, temporal_burst_score, fetch_cluster_snapshot, compute_features, SupernodeAnomalyScorer, MIN_POPULATION
from nebula_f import FakeNebulaClient

def load_schema():
    with open(PRESETS / "schema.yaml") as file:
        return yaml.safe_load(file)

def build_row(record_id, email=None, phone=None, transaction_date="2026-01-01T00:00:00", merchant_name="abc", screen_width="1000", screen_length="800", ip_country="us", city="New York", language="en-US"):
    def sha(v):
        return hashlib.sha256(v.strip().lower().encode("utf-8")).hexdigest() if v else None
    
    return {
        "record_id": record_id, "source_table": "orders", "transaction_date": transaction_date, "merchant_name": merchant_name, "merchant_url": "https://abc.com", "hashed_email": sha(email),
        "hashed_phone": sha(phone), "maid": None, "screen_width": screen_width, "screen_length": screen_length, "ip_country": ip_country, "city": city, "language": language
    }

def build_identity(nebula, schema_cols, raw_rows):
    rows = [GraphRow.from_db_row(r, schema_cols) for r in raw_rows]
    for row in rows:
        nebula.execute_many(row_to_ngql(row))
    identifiers = {vid(id_type, val) for row in rows for id_type, val in row.identifiers.items() if val}
    
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

class TemporalBurstTests(unittest.TestCase):
    def test_empty_single(self):
        self.assertEqual(temporal_burst_score([]), 0.0)
        self.assertEqual(temporal_burst_score([datetime.datetime(2024, 1, 1)]), 0.0)

    def test_wide_spaced(self):
        base = datetime.datetime(2025, 1, 1, 8, 0, 0)
        dates = [base, base + datetime.timedelta(days=30), base + datetime.timedelta(days=90)]
        self.assertEqual(temporal_burst_score(dates), 0.0)

    def test_tight_spaced(self):
        base = datetime.datetime(2025, 1, 1, 8, 0, 0)
        dates = [base, base + datetime.timedelta(minutes=5), base + datetime.timedelta(minutes=10)]
        self.assertEqual(temporal_burst_score(dates), 1.0)

    def test_mixed(self):
        base = datetime.datetime(2025, 1, 1, 8, 0, 0)
        dates = [base, base + datetime.timedelta(minutes=5), base + datetime.timedelta(days=60)]
        self.assertAlmostEqual(temporal_burst_score(dates), 2 / 3)

class FetchAndComputeTests(unittest.TestCase):
    def setUp(self):
        self.schema_cols = load_schema()
        self.nebula = FakeNebulaClient()

    def test_unflushed_identity(self):
        snapshot = fetch_cluster_snapshot("id1", self.nebula, self.schema_cols)
        self.assertEqual(snapshot, {})
        features = compute_features("id1", snapshot)
        self.assertEqual(features.record_count, 0)
        self.assertEqual(features.identifier_count, 0)

    def test_single_record(self):
        identity = build_identity(self.nebula, self.schema_cols, [build_row("r1", email="a@gmail.com", phone="12345678")])
        snapshot = fetch_cluster_snapshot(identity, self.nebula, self.schema_cols)
        features = compute_features(identity, snapshot)
        self.assertEqual(features.record_count, 1)
        self.assertEqual(features.identifier_count, 2)
        self.assertEqual(features.signal_diversity, 0.0)
        self.assertEqual(features.temporal_burst, 0.0)

    def test_supernode_burst_diversity(self):
        rows = [build_row(f"r-{i}", email="b@gmail.com", phone=f"12345678{i}", transaction_date=f"2026-06-01T00:0{i}:00", screen_width=(1000 + i * 50), city=f"City{i}") for i in range(1, 6)]
        identity = build_identity(self.nebula, self.schema_cols, rows)
        snapshot = fetch_cluster_snapshot(identity, self.nebula, self.schema_cols)
        features = compute_features(identity, snapshot)
        self.assertEqual(features.record_count, 5)
        self.assertEqual(features.identifier_count, 6)
        self.assertEqual(features.signal_diversity, 1.0)
        self.assertEqual(features.temporal_burst, 1.0)

class SupernodeAnomalyScorerTests(unittest.TestCase):
    def setUp(self):
        self.schema_cols = load_schema()
        self.nebula = FakeNebulaClient()
        self.scorer = SupernodeAnomalyScorer()

    def test_unflushed_identity(self):
        result = self.scorer.score("id1", self.nebula, self.schema_cols)
        self.assertFalse(result.is_anomalous)
        self.assertIn("zero transactions inserted in graph db", result.reason)
        self.assertEqual(self.scorer.stats["identifier_count"].n, 0)

    def test_cold_start(self):
        for i in range(MIN_POPULATION - 1):
            rows = [build_row(f"r{i}{j}", email=f"a{i}@gmail.com", phone=f"12345{i}", transaction_date=f"2026-01-00T00:{j:02d}:00") for j in range(i + 1)]
            identity = build_identity(self.nebula, self.schema_cols, rows)        
            result = self.scorer.score(identity, self.nebula, self.schema_cols)
            self.assertFalse(result.population_ready)
            self.assertFalse(result.is_anomalous)

    def add_data(self):
        rows = [
            [build_row("r-1", email="r1@gmail.com", phone="12345678")],
            [build_row("r-2", email="r2@gmail.com", transaction_date="2026-01-01T00:00:00"),
             build_row("r-3", email="r2@gmail.com", transaction_date="2026-03-01T00:00:00", screen_width="390")],
             [build_row("r-4", phone="123456789")],
            [build_row("r-5", email="r5@gmail.com", phone="87654321", transaction_date="2026-01-01T00:00:00"),
             build_row("r-6", email="r5@gmail.com", phone="87654321", transaction_date="2026-01-01T00:40:00")],
            [build_row("r-7", email="r7@gmail.com")],
            [build_row("r-8", email="r8@gmail.com", phone="123456789", transaction_date="2026-01-01T00:00:00"),
             build_row("r-9", email="r8@gmail.com", phone="123456789", transaction_date="2026-04-01T00:00:00"),
             build_row("r-10", email="r8@gmail.com", phone="123456789", transaction_date="2026-08-01T00:00:00", screen_width="360")
             ]]
        for batch in rows:
            identity = build_identity(self.nebula, self.schema_cols, batch)
            self.scorer.score(identity, self.nebula, self.schema_cols)

    def test_supernode_against_clusters(self):
        self.add_data()
        rows = [build_row(f"anomaly{i}", email="abc@gmail.com", phone=f"12345678{i}", transaction_date=f"2026-01-01T00:0{i}:00", screen_width=f"{1200 + i * 50}", city=f"Town{i}") for i in range(1, 7)]
        identity = build_identity(self.nebula, self.schema_cols, rows)
        result = self.scorer.score(identity, self.nebula, self.schema_cols)
        self.assertTrue(result.population_ready)
        self.assertTrue(result.is_anomalous)
        self.assertLess(result.features.identifier_count, 10)

    def test_ordinary_identity_check(self):
        self.add_data()
        rows = [build_row("r2", email="ab@gmail.com", phone="1234567891")]
        identity = build_identity(self.nebula, self.schema_cols, rows)
        result = self.scorer.score(identity, self.nebula, self.schema_cols)
        self.assertFalse(result.is_anomalous)


if __name__ == "__main__":
    unittest.main()