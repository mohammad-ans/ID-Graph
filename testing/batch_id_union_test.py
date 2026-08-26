from __future__ import annotations
import sys
import unittest
from pathlib import Path

MAIN_DIR = Path(__file__).parent.parent / "main"
sys.path.insert(0, str(MAIN_DIR))

from batch_id_union import UnionFind, cluster_identifiers
from graph_model import GraphRow

SCHEMA_COLS = {
    "identifiers" : [
        {"name": "email", "column": "hashed_email", "pre_hashed": True, "include_in_belongs_to": True},
        {"name": "phone", "column": "hashed_phone", "pre_hashed": True, "include_in_belongs_to": True},
        {"name": "maid", "column": "maid", "pre_hashed": False, "include_in_belongs_to": False}
    ],
    "signal_groups": [
        {"name":"device_props", "columns": ["screen_width", "screen_length"]},
        {"name": "ip_loc", "columns": ["ip_country", "city", "language"]}
    ],
    "passthrough": ["transaction_date", "merchant_name", "merchant_url", "source_table"],
    "record_id": ["record_id"]
}

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