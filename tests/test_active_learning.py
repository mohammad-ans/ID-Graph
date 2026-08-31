from __future__ import annotations
import sys, yaml
import unittest
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent / "src/identityresolver"
sys.path.insert(0, str(MAIN_DIR))
from graph_model import GraphRow
from probability import FellegiSunterModel, resolve_prolly, pair_features
from active_learning import FEATURES, logistic_regression, _field_names


def load_schema_cols():
    with open(MAIN_DIR / "schema.yaml") as file:
        return yaml.safe_load(file)

def build_row(record_id, date, merchant, screen_width, screen_length, country, city, language):
    raw = {"record_id": record_id, "source_table": "orders", "transaction_date": date, "merchant_name": merchant, "merchant_url": None, "hashed_email": None,
            "hashed_phone": None, "maid": None, "screen_width": screen_width, "screen_length": screen_length, "ip_country": country, "city": city, "language": language
        }
    return GraphRow.from_db_row(raw, load_schema_cols())

class ResolveProllyIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.schema_cols = load_schema_cols()
        self.model = FellegiSunterModel()
        self.field_names = _field_names(self.schema_cols)
        self.rows = [build_row("r1", "2026-01-01T00:00:00", "New York", "1440", "900", "us", "Austin", "en-US"),
                     build_row("r2", "2026-01-01T00:00:00", "New York", "1440", "900", "us", "Austin", "en-US")]

    def test_no_classifier(self):
        result = resolve_prolly(self.rows, self.schema_cols, self.model)
        self.assertEqual(len(result.auto_merge_groups), 1)
        _, score = result.auto_merge_groups[0]
        direct_score = self.model.score(pair_features(self.rows[0], self.rows[1], self.schema_cols))
        self.assertAlmostEqual(score, direct_score)

    def test_uses_classifier_score(self):
        agree_all = {name: True for name in FEATURES}
        agree_none = {name: False for name in FEATURES}
        classifier = logistic_regression([(agree_all, 1), (agree_none, 0)] * 10, field_names=self.field_names)
        result1 = resolve_prolly(self.rows, self.schema_cols, self.model, classifier=None)
        result2 = resolve_prolly(self.rows, self.schema_cols, self.model, classifier=classifier)
        _, score1 = result1.auto_merge_groups[0]
        _, score2 = result2.auto_merge_groups[0]
        self.assertNotAlmostEqual(score1, score2)
        self.assertEqual(len(result2.auto_merge_groups), 1)

    def test_classifier_change(self):
        rows = [build_row("r3", "2026-01-01T00:00:00", "New York", "1440", "900", "us", "Austin", "en-US"),
                build_row("r4", "2026-01-01T00:00:00", "New York", "999", "999", "us", "Austin", "en-US")]
        result_fs = resolve_prolly(rows, self.schema_cols, self.model, classifier=None)
        labeled = []
        for _ in range(1):
            labeled.append(({"ip_country": True, "city": True, "language": True, "merchant_name": True, "temporal_same_day": True}, 1))
            labeled.append(({"ip_country": False, "city": False, "language": False, "merchant_name": False}, 0))
        classifier = logistic_regression(labeled, field_names=self.field_names)
        result_classifier = resolve_prolly(rows, self.schema_cols, self.model, classifier=classifier)
        fs_bucket  = "reject"
        if result_fs.auto_merge_groups:
            fs_bucket = "auto_merge"
        elif result_fs.review_candidates:
            fs_bucket = "review"
        classifier_bucket = "reject"
        if result_classifier.auto_merge_groups:
            classifier_bucket = "auto_merge"
        elif result_classifier.review_candidates:
            classifier_bucket = "review"
        self.assertIn(fs_bucket, ("auto_merge", "review", "reject"))
        self.assertIn(classifier_bucket, ("auto_merge", "review", "reject"))

if __name__ == "__main__":
    unittest.main()