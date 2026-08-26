from __future__ import annotations
import sys, yaml, hashlib
import unittest
from pathlib import Path

MAIN_DIR = Path(__file__).parent.parent / "main"
DEMO_DIR = Path(__file__).parent.parent / "demo"

sys.path.insert(0, str(MAIN_DIR))
sys.path.insert(0, str(DEMO_DIR))

from cluster_union_strict import UnionFind, generate_pairs, is_identifier_check

def load_schema_cols():
    with open(MAIN_DIR / "schema.yaml") as file:
        return yaml.safe_load(file)

def build_row(record_id, email=None, phone=None, screen_width="1000", city="New York"):
    def sha(v):
        return hashlib.sha256(v.strip().lower().encode("utf-8")).hexdigest() if v else None

    return {
        "record_id": record_id, "source_table": "orders", "transaction_date": "2024-01-01T00:00:00", "merchant_name": "Test", "merchant_url": None, "hashed_email": sha(email),
        "hashed_phone": sha(phone), "maid": None, "screen_width": screen_width, "screen_length": "800", "ip_country": "us", "city": city, "language": "en-US"
    }

class PairUnionFindTests(unittest.TestCase):
    def test_separate_clusters(self):
        uf = UnionFind()
        uf.union([("a", "x")])
        uf.union([("b", "y")])
        self.assertNotEqual(uf.pair_cluster[("a", "x")], uf.pair_cluster[("b", "y")])

    def test_overlapping_clusters(self):
        uf = UnionFind()
        uf.union([("a", "x")])
        uf.union([("b", "y")])
        uf.union([("a", "x"), ("z", "w")])
        self.assertEqual(uf.pair_cluster[("a", "x")], uf.pair_cluster[("z", "w")])
        self.assertNotEqual(uf.pair_cluster[("b", "y")], uf.pair_cluster[("z", "w")])

    def test_single(self):
        uf = UnionFind()
        uf.union([("a@gmail.com", "person_a")])
        uf.union([("a@gmail.com", "person_b")])
        self.assertNotEqual(uf.pair_cluster[("a@gmail.com", "person_a")], uf.pair_cluster[("a@gmail.com", "person_b")])

class GeneratePairTests(unittest.TestCase):
    def test_allPairs(self):
        pairs = generate_pairs(["email:a", "phone:a"], ["maid:device"])
        self.assertIn(("email:a", "maid:device"), pairs)
        self.assertIn(("phone:a", "maid:device"), pairs)
        self.assertIn(("email:a", "phone:a"), pairs)

    def test_none_signals(self):
        pairs = generate_pairs(["email:a"], [None])
        self.assertEqual(pairs, [])

class IsIdentifierTests(unittest.TestCase):
    def test_valid_identifier(self):
        self.assertTrue(is_identifier_check(["email", "phone"], "email:abc123"))
    def test_reject_identifier(self):
        self.assertFalse(is_identifier_check(["email", "phone"], "dummy"))