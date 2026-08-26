from __future__ import annotations
import sys, yaml, hashlib
import unittest
from pathlib import Path

MAIN_DIR = Path(__file__).parent.parent / "main"
DEMO_DIR = Path(__file__).parent.parent / "demo"

sys.path.insert(0, str(MAIN_DIR))
sys.path.insert(0, str(DEMO_DIR))

from cluster_union_strict import UnionFind, generate_pairs, is_identifier_check, cluster_identifiers_strict
from nebula_f import FakeNebulaClient
from graph_model import GraphRow, row_to_ngql, vid, add_identity

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

class ClusterIdentifiersStrictTests(unittest.TestCase):
    def setUp(self):
        self.schema_cols = load_schema_cols()
        self.nebula = FakeNebulaClient()
    def build_identity(self, raw_rows):
        rows = [GraphRow.from_db_row(row, self.schema_cols) for row in raw_rows]
        for row in rows:
            self.nebula.execute_many(row_to_ngql(row))
        identifiers = set()
        for row in rows:
            identifiers.update({vid(id_type, val) for id_type, val in row.identifiers.items() if val})
        statements, identity = add_identity(identifiers)
        self.nebula.execute_many(statements)
        return identity

    def test_return_none_liveData_not_flushed(self):
        result = cluster_identifiers_strict("uid:r1", self.nebula, self.schema_cols)
        self.assertIsNone(result)

    def test_split_unrelated(self):
        rows = [build_row(f"r{i}", email="a@gmail.com", phone=f"1234567{i}", screen_width=str(1000 + i * 50), city=f"City{i}") for i in range(4)]
        identity = self.build_identity(rows)
        result = cluster_identifiers_strict(identity, self.nebula, self.schema_cols)
        self.assertIsNotNone(result)
        cluster_identifier, _, _, _ = result
        self.assertEqual(len(cluster_identifier), 4)

    def test_not_split_related(self):
        rows = [build_row("r1", email="a@gmail.com", phone="12345678", screen_width="1440"),
            build_row("r2", email="a@gmail.com", phone="12345678", screen_width="1440")]
        identity = self.build_identity(rows)
        result = cluster_identifiers_strict(identity, self.nebula, self.schema_cols)
        self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()