import unittest
import sys, hashlib, yaml, math
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent / "main"
sys.path.insert(0, str(MAIN_DIR))

# from main.probability import pair_features, FellegiSunterModel
# from main.graph_model import GraphRow
from probability import pair_features, FellegiSunterModel
from graph_model import GraphRow

def load_schema():
    with open(MAIN_DIR / "schema.yaml") as file:
        return yaml.safe_load(file)

def build_row(record_id, email=None, phone=None, transaction_date="2026-01-01T00:00:00", merchant_name=None, screen_width=None, screen_length=None, ip_country="us", city="New York", language="en-US"):
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
        a = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-01-01T00:00:00", merchant_name="M", screen_width="1600", screen_length="900", ip_country="us", city="New York", language="en-US"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r2", transaction_date="2026-01-01T00:00:00", merchant_name="M2", screen_width="1600", screen_length="900", city="New York", ip_country="us", language="en-US"), self.schema)
        features = pair_features(a, b, self.schema)
        self.assertTrue(features["screen_width"] and features["screen_length"] and features["ip_country"] and features["temporal_same_day"] and features["temporal_same_week"] and features["temporal_same_month"] and not features["merchant_name"])

    def test_different_records(self):
        a = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-01-01T00:00:00", merchant_name="M", screen_width="1600", screen_length="900", ip_country="us", city="New York", language="en-US"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r2", transaction_date="2026-10-09T00:00:00", merchant_name="M2", screen_width="390", screen_length="390", ip_country="ind", city="Delhi", language="Hindi"), self.schema)
        features = pair_features(a, b, self.schema)
        self.assertFalse(any(features.values()))

    def missing_value(self):
        a = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-01-01T00:00:00", merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"),self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-01-01T00:00:00", merchant_name="M", screen_width=None, screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        features = pair_features(a, b, self.schema)
        self.assertTrue(features["screen_length"] and not features["screen_width"])

    def test_temporal_buckets(self):
        a = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-01-01T00:00:00", merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-01-01T08:00:00", merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        c = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-01-04T00:00:00", merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        d = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-01-09T00:00:00", merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        e = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-04-09T00:00:00", merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        features = pair_features(a, b, self.schema)
        self.assertTrue(features["temporal_same_day"] and features["temporal_same_week"] and features["temporal_same_month"])
        features = pair_features(a, c, self.schema)
        self.assertTrue(not features["temporal_same_day"] and features['temporal_same_week'] and features["temporal_same_month"])
        features = pair_features(a, d, self.schema)
        self.assertFalse(features["temporal_same_day"] or features["temporal_same_week"] or not features["temporal_same_month"])
        features = pair_features(a, e, self.schema)
        self.assertFalse(features["temporal_same_day"] or features["temporal_same_week"] or features["temporal_same_month"])

    def test_missing_date(self):
        a = GraphRow.from_db_row(build_row(record_id="r1", transaction_date=None, merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r2", transaction_date="2026-01-01T00:00:00", merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        features = pair_features(a, b, self.schema)
        self.assertFalse(features["temporal_same_day"])


class TestFellegiSunterModel(unittest.TestCase):
    def setUp(self):
        self.model = FellegiSunterModel()   
        self.schema = load_schema()

    def test_no_agreement(self):
        a = GraphRow.from_db_row(build_row(record_id="r1", transaction_date="2026-01-01T00:00:00", merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r2", transaction_date="2026-03-01T00:00:00", merchant_name="M2", screen_width="391", screen_length="391", ip_country="ind", city="Delhi", language="Hindi"), self.schema)
        score = self.model.score(pair_features(a, b, self.schema))
        self.assertTrue(score < 0.01)

    def test_full_agreement(self):
        a = GraphRow.from_db_row(build_row(record_id="r3", transaction_date="2026-01-01T00:00:00", merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r4", transaction_date="2026-01-01T00:00:00", merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        score = self.model.score(pair_features(a, b, self.schema))
        self.assertTrue(score > 0.99)

    def test_score_valid_probability(self):
        a = GraphRow.from_db_row(build_row(record_id="r5", transaction_date="2026-01-01T00:00:00", merchant_name="M", screen_width="390", screen_length="390", ip_country="us", city="New York", language="en-US"), self.schema)
        b = GraphRow.from_db_row(build_row(record_id="r6", transaction_date="2026-01-02T00:00:00", merchant_name="M2", screen_width="390", screen_length=None, ip_country="us", city=None, language="en-US"), self.schema)
        score = self.model.score(pair_features(a, b, self.schema))
        self.assertTrue(0.0 <= score <= 1.0)

    def test_extreme_priors(self):
        model = FellegiSunterModel(m_probs={"x": 0.999999}, u_probs={"x": 0.000001}, prior_match_prolly=0.5)
        score = model.score({"x": True})
        self.assertFalse(math.isnan(score) or math.isinf(score))
        score2 = model.score({"x": False})
        self.assertFalse(math.isnan(score2) or math.isinf(score2))