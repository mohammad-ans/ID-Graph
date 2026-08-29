import unittest
import sys, hashlib, yaml, math
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent / "main"
sys.path.insert(0, str(MAIN_DIR))

from probability import pair_features, FellegiSunterModel, blocking_key, generate_candidates, PoolRow, generate_cross_batch_candidates, group_auto_merging, resolve_prolly, should_refit, MIN_HISTORY, score_guest
from graph_model import GraphRow

def load_schema():
    with open(MAIN_DIR / "schema.yaml") as file:
        return yaml.safe_load(file)

def build_row(record_id, email=None, phone=None, transaction_date="2026-01-01T00:00:00", merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"):
    def sha(v):
        return hashlib.sha256(v.strip().lower().encode("utf-8")).hexdigest if v else None
    return {
        "record_id": record_id, "source_table": "orders", "transaction_date": transaction_date, "merchant_name": merchant_name, "merchant_url": "https://abc.com", "hashed_email": sha(email), 
        "hashed_phone": sha(phone), "maid": None, "screen_width": screen_width, "screen_length": screen_length, "ip_country": ip_country, "city": city, "language": language
    }

class TestPairFeatures(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()
    def test_identical_devices_location(self):
        a = GraphRow.from_db_row(build_row(record_id="r1", merchant_name="M", screen_width="1600", screen_length="900", ip_country="us", city="New York", language="en-US"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r2", merchant_name="M2", screen_width="1600", screen_length="900", city="New York", ip_country="us", language="en-US"), self.schema)
        features = pair_features(a, b, self.schema)
        self.assertTrue(features["screen_width"] and features["screen_length"] and features["ip_country"] and features["temporal_same_day"] and features["temporal_same_week"] and features["temporal_same_month"] and not features["merchant_name"])

    def test_different_records(self):
        a = GraphRow.from_db_row(build_row(record_id="r1", merchant_name="M", screen_width="1600", screen_length="900", ip_country="us", city="New York", language="en-US"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r2", transaction_date="2026-10-09T00:00:00", merchant_name="M2", screen_width="390", screen_length="390", ip_country="ind", city="Delhi", language="Hindi"), self.schema)
        features = pair_features(a, b, self.schema)
        self.assertFalse(any(features.values()))

    def missing_value(self):
        a = GraphRow.from_db_row(build_row(record_id="r1"),self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r1", merchant_name="M", screen_width=None, screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        features = pair_features(a, b, self.schema)
        self.assertTrue(features["screen_length"] and not features["screen_width"])

    def test_temporal_buckets(self):
        a = GraphRow.from_db_row(build_row(record_id="r1"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-01-01T08:00:00"), self.schema)
        c = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-01-04T00:00:00"), self.schema)
        d = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-01-09T00:00:00"), self.schema)
        e = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-04-09T00:00:00"), self.schema)
        features = pair_features(a, b, self.schema)
        self.assertTrue(features["temporal_same_day"] and features["temporal_same_week"] and features["temporal_same_month"])
        features = pair_features(a, c, self.schema)
        self.assertTrue(not features["temporal_same_day"] and features['temporal_same_week'] and features["temporal_same_month"])
        features = pair_features(a, d, self.schema)
        self.assertFalse(features["temporal_same_day"] or features["temporal_same_week"] or not features["temporal_same_month"])
        features = pair_features(a, e, self.schema)
        self.assertFalse(features["temporal_same_day"] or features["temporal_same_week"] or features["temporal_same_month"])

    def test_missing_date(self):
        a = GraphRow.from_db_row(build_row(record_id="r1", transaction_date=None), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r2"), self.schema)
        features = pair_features(a, b, self.schema)
        self.assertFalse(features["temporal_same_day"])


class TestFellegiSunterModel(unittest.TestCase):
    def setUp(self):
        self.model = FellegiSunterModel()   
        self.schema = load_schema()

    def test_no_agreement(self):
        a = GraphRow.from_db_row(build_row(record_id="r1"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r2", transaction_date="2026-03-01T00:00:00", merchant_name="M2", screen_width="391", screen_length="391", ip_country="ind", city="Delhi", language="Hindi"), self.schema)
        score = self.model.score(pair_features(a, b, self.schema))
        self.assertTrue(score < 0.01)

    def test_full_agreement(self):
        a = GraphRow.from_db_row(build_row(record_id="r3"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r4"), self.schema)
        score = self.model.score(pair_features(a, b, self.schema))
        self.assertTrue(score > 0.99)

    def test_score_valid_probability(self):
        a = GraphRow.from_db_row(build_row(record_id="r5"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r6", transaction_date="2026-01-02T00:00:00", merchant_name="M2", screen_width="390", screen_length=None, ip_country="us", city=None, language="en-US"), self.schema)
        score = self.model.score(pair_features(a, b, self.schema))
        self.assertTrue(0.0 <= score <= 1.0)

    def test_extreme_priors(self):
        model = FellegiSunterModel(m_probs={"x": 0.999999}, u_probs={"x": 0.000001}, prior_match_prolly=0.5)
        score = model.score({"x": True})
        self.assertFalse(math.isnan(score) or math.isinf(score))
        score2 = model.score({"x": False})
        self.assertFalse(math.isnan(score2) or math.isinf(score2))

class TestBlockingKey(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()
    def test_grouping(self):
        schema = load_schema()
        a = GraphRow.from_db_row(build_row(record_id="r1"), schema)
        b = GraphRow.from_db_row(build_row(record_id="r2"), schema)
        c = GraphRow.from_db_row(build_row(record_id="r3", transaction_date="2026-07-01T00:00:00", merchant_name="M", screen_width="390", screen_length="390", city="Delhi", ip_country="ind", language="Hindi"), schema)
        self.assertTrue(blocking_key(a, self.schema) == blocking_key(b, self.schema))
        self.assertTrue(blocking_key(a, self.schema) != blocking_key(c, self.schema))

class TestGenerateCandidates(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()
    def test_same_block_candidates(self):
        rows = [GraphRow.from_db_row(build_row(record_id="r1"), self.schema),
            GraphRow.from_db_row(build_row(record_id="r2"), self.schema),
            GraphRow.from_db_row(build_row(record_id="r3", transaction_date="2026-07-01T00:00:00", merchant_name="M", screen_width="390", screen_length="390", city="Delhi", ip_country="ind", language="Hindi"), self.schema)]
        candidates = generate_candidates(rows, self.schema)
        pairs = {(x.record_id, y.record_id) for x, y in candidates}
        self.assertTrue(("r1", "r2") in pairs)
        self.assertFalse(("r1", "r3") in pairs)
        

    def test_single_row(self):
        rows = [GraphRow.from_db_row(build_row(record_id="r1"), self.schema)]
        self.assertEqual(generate_candidates(rows, self.schema), [])

    def test_max_block_size(self):
        rows = [GraphRow.from_db_row(build_row(record_id=f"r{i}"), self.schema) for i in range(10)]
        candidates = generate_candidates(rows, self.schema, max_block_size=5)
        print(len(candidates))
        self.assertEqual(len(candidates), 10)

    def test_cross_batch_noAll_pool(self):
        rows = [GraphRow.from_db_row(build_row(record_id="r1"), self.schema)]
        pool_rows = [PoolRow.from_graph_row(GraphRow.from_db_row(build_row(record_id="r2"), self.schema)),
         PoolRow.from_graph_row(GraphRow.from_db_row(build_row(record_id="r3"), self.schema))]
        candidates = generate_cross_batch_candidates(rows, pool_rows, self.schema)
        pairs = [(x.record_id, y.record_id) for x, y in candidates]
        self.assertTrue(("r1", "r2") in pairs)
        self.assertTrue(("r1", "r3") in pairs)
        self.assertFalse(("r2", "r3") in pairs)

    def test_blocking_key_for_pool_rows(self):
        rows = [GraphRow.from_db_row(build_row(record_id="r1"), self.schema)]
        pool_rows = [PoolRow.from_graph_row(GraphRow.from_db_row(build_row(record_id="r2", transaction_date="2026-02-02T00:00:00"), self.schema))]
        candidates = generate_cross_batch_candidates(rows, pool_rows, schema_cols=self.schema)
        self.assertEqual(candidates, [])

class TestGroupAutoMerge(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()
    def test_chains_form_oneGroup(self):
        a = GraphRow.from_db_row(build_row(record_id="r1"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r2"), self.schema)
        c = GraphRow.from_db_row(build_row(record_id="r3"), self.schema)
        scored = [(a, b, 0.95, {}), (b, c, 0.92, {})]
        groups = group_auto_merging(scored)
        rows, score = groups[0]
        self.assertEqual({r.record_id for r in rows}, {"r1", "r2", "r3"})
        self.assertAlmostEqual(score, (0.95 + 0.92) / 2)

    def test_disjoint_pairs(self):
        a = GraphRow.from_db_row(build_row(record_id="r1"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r2"), self.schema)
        c = GraphRow.from_db_row(build_row(record_id="r3"), self.schema)
        d = GraphRow.from_db_row(build_row(record_id="r4"), self.schema)
        scored = [(a, b, 0.95, {}), (c, d, 0.93, {})]
        groups = group_auto_merging(scored)
        self.assertEqual(len(groups), 2)

    def test_empty_no_groups(self):
        self.assertEqual(group_auto_merging([]), [])

class TestResolveProbabilistically(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()
    def test_matching_pair(self):
        rows = [GraphRow.from_db_row(build_row(record_id="r1"), self.schema), GraphRow.from_db_row(build_row(record_id="r2", transaction_date="2026-01-01T06:00:00"), self.schema)]
        result = resolve_prolly(rows, self.schema)
        self.assertEqual(len(result.auto_merge_groups), 1)
        self.assertEqual({r.record_id for r in result.auto_merge_groups[0][0]}, {"r1", "r2"})
        self.assertEqual(result.unmatched_new, [])
    def test_nonmatching_pair(self):
        rows = [GraphRow.from_db_row(build_row(record_id="r1"), self.schema), GraphRow.from_db_row(build_row(record_id="r2", transaction_date="2026-08-01T00:00:00", merchant_name="M2", screen_width="391", screen_length="391", city="Delhi", ip_country="ind", language="hindi"), self.schema)]
        result = resolve_prolly(rows, self.schema)
        self.assertEqual(result.auto_merge_groups, [])
        self.assertEqual(result.rejected_count, 0)
    def test_single_row(self):
        rows = [GraphRow.from_db_row(build_row("r1"), self.schema)]
        result = resolve_prolly(rows, self.schema)
        self.assertEqual(result.auto_merge_groups, [])
        self.assertEqual([r.record_id for r in result.unmatched_new], ["r1"])
    def test_all_scored(self):
        rows = [GraphRow.from_db_row(build_row(record_id="r1"), self.schema), GraphRow.from_db_row(build_row(record_id="r2", merchant_name="M2"), self.schema),
            GraphRow.from_db_row(build_row(record_id="r3", merchant_name="M3", screen_width="391", screen_length="391", city="Austin"), self.schema)]
        result = resolve_prolly(rows, self.schema)
        outcomes = {outcome for *_, outcome in result.all_scored}
        self.assertTrue("auto_merge" in outcomes)
        self.assertEqual(len(result.all_scored), 3)
    def test_poolRow_match_marking_consumed(self):
        rows = [GraphRow.from_db_row(build_row("r1"), self.schema)]
        pool_rows = [PoolRow.from_graph_row(GraphRow.from_db_row(build_row("r2", transaction_date="2026-01-04T00:00:00", merchant_name="M2"), self.schema))]
        result = resolve_prolly(rows, self.schema, pool_rows=pool_rows)
        self.assertEqual(result.matched_pool_records, {"r2"})
        self.assertEqual(result.unmatched_new, [])
        self.assertEqual(len(result.auto_merge_groups), 1)

    def test_poolRow_nonMatch_untouched(self):
        rows = [GraphRow.from_db_row(build_row("r1"), self.schema)]
        pool_rows = [PoolRow.from_graph_row(GraphRow.from_db_row(build_row("r2", transaction_date="2026-08-01T00:00:00", merchant_name="M2", screen_width="391", screen_length="391", city="Delhi"), self.schema))]
        result = resolve_prolly(rows, self.schema, pool_rows=pool_rows)
        self.assertEqual(result.matched_pool_records, set())
        self.assertEqual([r.record_id for r in result.unmatched_new], ["r1"])

class TestFitEm(unittest.TestCase):
    def setUp(self):
        self.model = FellegiSunterModel()
        self.schema = load_schema()
    def test_fitem_empty_history(self):
        before = dict(self.model.m_probs)
        self.model.fit_em([])
        self.assertEqual(self.model.m_probs, before)
    def test_fitem_moves_parameters_from_priors(self):
        before = dict(self.model.m_probs)
        rows = []
        for i in range(20):
            rows.append(GraphRow.from_db_row(build_row(f"r{i}"), self.schema))
            rows.append(GraphRow.from_db_row(build_row(f"r-{i}"), self.schema))
        features = []
        for i in range(0, len(rows) - 1, 2):
            features.append(pair_features(rows[i], rows[i + 1], self.schema))
        self.model.fit_em(features)
        self.assertNotEqual(self.model.m_probs, before)
        for v in list(self.model.m_probs.values()) + list(self.model.u_probs.values()):
            self.assertTrue(0.0 <= v <= 1.0)
            self.assertFalse(math.isnan(v))
    def test_fitem_no_literal_zero_one(self):
        self.model = FellegiSunterModel()
        rows = [GraphRow.from_db_row(build_row(f"r{i}"), self.schema) for i in range(10)]
        features = []
        for i in range(9):
            features.append(pair_features(rows[i], rows[i + 1], self.schema))
        self.model.fit_em(features)
        for v in list(self.model.m_probs.values()) + list(self.model.u_probs.values()):
            self.assertTrue(0.0 < v < 1.0)

    def test_should_refitem_respects_threshold(self):
        self.assertFalse(should_refit(MIN_HISTORY - 1))
        self.assertTrue(should_refit(MIN_HISTORY))
        self.assertFalse(should_refit(9, 10))
        self.assertTrue(should_refit(10, 10))

class TestReconciliation(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()
    def test_weak_strong_candidates(self):
        pool_rows = [PoolRow.from_graph_row(GraphRow.from_db_row(build_row("r1"), self.schema), "id1"),
            PoolRow.from_graph_row(GraphRow.from_db_row(build_row("r2", transaction_date="2026-01-01T09:00:00", merchant_name="M2"), self.schema), "id1"),
            PoolRow.from_graph_row(GraphRow.from_db_row(build_row("r3", transaction_date="2026-01-01T01:00:00", merchant_name="M3", screen_width="391", screen_length="391", city="Austin", language="abc"), self.schema), "id2")]
        row = GraphRow.from_db_row(build_row("r4", transaction_date="2026-01-01T10:00:00", email="a@gmail.com"), self.schema)
        results = score_guest(row, pool_rows, self.schema)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].probable_identity, "id1")
        self.assertEqual(results[0].member_records, ["r1", "r2"])
    def test_no_candidates(self):
        row = GraphRow.from_db_row(build_row("r1"), self.schema)
        self.assertEqual(score_guest(row, [], self.schema), [])