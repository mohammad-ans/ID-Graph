from __future__ import annotations
import sys, yaml
import unittest
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent / "main"
sys.path.insert(0, str(MAIN_DIR))

from batch_id_union import UnionFind, cluster_identifiers, distinct_identifiers, InvalidIdentifiers, parse_date, valid_identifiers
from graph_model import GraphRow

SCHEMA_COLS = None
with open(MAIN_DIR / "schema.yaml") as file:
    SCHEMA_COLS = yaml.safe_load(file)

def row(record_id, email=None, phone=None, transaction_date=None):
    return GraphRow.from_db_row({"record_id": record_id, "source_table": "orders", "transaction_date": transaction_date, "merchant_name": "Test", "merchant_url": None, "hashed_email": email, "hashed_phone": phone, "maid": None, "screen_width": None, "screen_length": None, "ip_country": None, "city": None, "language": None}, SCHEMA_COLS)

class UnionFindTests(unittest.TestCase):
    def test_union_find_related(self):
        uf = UnionFind()
        uf.union("a", "b")
        uf.union("a", "c")
        self.assertEqual(uf.find("a"), uf.find("c"))

    def test_union_find_unrelated(self):
        uf = UnionFind()
        uf.union("a", "b")
        uf.find("x")
        self.assertNotEqual(uf.find("a"), uf.find("x"))

    def test_union_find_size(self):
        uf = UnionFind()
        uf.union("a", "b")
        uf.union("a", "c")
        uf.union("x", "a")
        self.assertEqual(uf.find("x"), uf.find("a"))
        self.assertEqual(uf.find("x"), uf.find("b"))

class ClusterIdentifiersTest(unittest.TestCase):
    def test_email_clusters(self):
        rows = [row("r1", email="a@gmail.com"), row("r2", email="a@gmail.com")]
        cluster_map, _, _ = cluster_identifiers(rows, {}, False, SCHEMA_COLS)
        self.assertEqual(len(cluster_map), 1)

    def test_separate_clusters(self):
        rows = [row("r1", email="a@gmail.com"), row("r2", "b@gmail.com")]
        cluster_map, _, _ = cluster_identifiers(rows, {}, False, SCHEMA_COLS)
        self.assertEqual(len(cluster_map), 2)

    def test_email_phone_bridge(self):
        rows = [row("r1", email="a@gmail.com", phone="12345678"), row("r2", phone="12345678")]
        cluster_map, _, _= cluster_identifiers(rows, {}, False, SCHEMA_COLS)
        self.assertEqual(len(cluster_map), 1)

    def test_phone_date(self):
        rows = [row("r1", phone="`12345678", transaction_date="2024-11-01T00:00:00"), row("r2", phone="12345678", transaction_date="2025-02-01T00:00")]
        _, dates, _ = cluster_identifiers(rows, {}, True, SCHEMA_COLS)
        phone_key = next(iter(dates))
        self.assertEqual(dates[phone_key].isoformat(), "2024-11-01T00:00:00")

    def test_distinct_identifiers(self):
        rows = [row("r1", email="a@gmail.com"), row("r2", email="b@gmail.com")]
        cluster_map, _, _ = cluster_identifiers(rows, {}, False, SCHEMA_COLS)
        flat = distinct_identifiers(cluster_map)
        self.assertEqual(len(flat), 2)

    def test_zero_identifiers(self):
        rows = [row("r1"), row("r2", email="a@gmail.com")]
        cluster_map, _, _ = cluster_identifiers(rows, {}, False, SCHEMA_COLS)
        self.assertEqual(len(cluster_map), 1)

class RelativeDataInvalidTests(unittest.TestCase):
    def test_small_batch(self):
        rows = [row(f"r{i}", email="a@gmail.com") for i in range(3)]
        invalid = InvalidIdentifiers(SCHEMA_COLS)
        invalid.invalid_relative_newD(rows)
        self.assertEqual(invalid.invalid_identifiers["email"], {})

    def test_identifier_blacklist(self):
        rows = [row(f"r{i}", email="a@gmail.com") for i in range(8)]
        invalid = InvalidIdentifiers(SCHEMA_COLS)
        invalid.invalid_relative_newD(rows)
        self.assertIn(rows[0].identifiers["email"], invalid.invalid_identifiers["email"])

    def test_scaling_invalid_threshold(self):
        rows = [row(f"r{i}", email=f"a{i}@gmail.com") for i in range(200)]
        rows += [row(f"r-{i}", email="a@gmail.com") for i in range(8)]
        invalid = InvalidIdentifiers(SCHEMA_COLS)
        invalid.invalid_relative_newD(rows)
        self.assertEqual(invalid.invalid_identifiers["email"], {})

class ParseDateTests(unittest.TestCase):
    def test_valid_date(self):
        self.assertIsNotNone(parse_date("2024-01-01T00:00:00"))
    def test_none_date(self):
        self.assertIsNone(parse_date(None))
    def test_invalid_date(self):
        self.assertIsNone(parse_date("Date"))

class ValidIdentifierTests(unittest.TestCase):
    def test_return_type(self):
        r = row("r1", email="a@gmail.com", phone="987654321")
        result = valid_identifiers(r, {"email": {}, "phone": {}}, SCHEMA_COLS)
        self.assertEqual(set(result), {f"email:{r.identifiers['email']}", f"phone:{r.identifiers['phone']}"})
    def test_none_identifiers(self):
        r = row("r1", email="a@gmail.com")
        result = valid_identifiers(r, {"email": {}, "phone": {}}, SCHEMA_COLS)
        self.assertEqual(len(result), 1)

    def test_skip_invalid(self):
        r = row("r1", email="a@gmail.com", phone="12345678")
        invalid = {"email": {r.identifiers["email"]: 99}, "phone": {}}
        result = valid_identifiers(r, invalid, SCHEMA_COLS)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].startswith("phone:"))

if __name__ == "__main__":
    unittest.main()