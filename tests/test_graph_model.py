from __future__ import annotations
import sys, yaml, hashlib
import unittest
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent / "src/identityresolver"
DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"
sys.path.insert(0, str(MAIN_DIR))
sys.path.insert(0, str(DEMO_DIR))

from nebula_f import FakeNebulaClient
from batch_id_union import cluster_identifiers, distinct_identifiers
from graph_model import GraphRow, normalize_token, normalize_loc, sha256_text, is_valid_maid, ngql_string, vid, record_vid, identifier_type, parse_date, row_to_ngql, belongs_to_identity, insert_edge, insert_vertex, update_edge, update_vertex

def load_schema_cols():
    with open(MAIN_DIR / "schema.yaml") as file:
        return yaml.safe_load(file)

def build_row(record_id, email=None, phone=None, transaction_date="2026-01-01T00:00:00", screen_width="1000", screen_length="800", ip_country="us", city="New York", language="en-US"):
    def sha(v):
        return hashlib.sha256(v.strip().lower().encode("utf-8")).hexdigest() if v else None
    return {
        "record_id": record_id, "source_table": "orders", "transaction_date": transaction_date, "merchant_name": "Test", "merchant_url": None, "hashed_email": sha(email),
        "hashed_phone": sha(phone), "maid": None, "screen_width": screen_width, "screen_length": screen_length, "ip_country": ip_country, "city": city, "language": language
    }

class HelperFunctionTests(unittest.TestCase):
    def test_normalize_token(self):
        self.assertEqual(normalize_token(" Hello World! "), "hello_world_")

    def test_normalize_token_none(self):
        self.assertIsNone(normalize_token(None))
        self.assertIsNone(normalize_token(""))

    def test_normalize_loc(self):
        self.assertEqual(normalize_loc("New York!"), "newyork")

    def test_normalize_loc_none(self):
        self.assertEqual(normalize_loc(None), "")

    def test_sha256_text(self):
        self.assertEqual(sha256_text("a@gmail.com"), sha256_text("A@GMAIL.COM"))
        self.assertEqual(len(sha256_text("x")), 64)

    def test_is_valid_maid(self):
        self.assertFalse(is_valid_maid("00000000-0000-0000-0000-000000000000"))
        self.assertFalse(is_valid_maid(None))
        self.assertFalse(is_valid_maid(""))
        self.assertTrue(is_valid_maid("abcdefgh-1234-1234-abcd-ab1234567890"))

    def test_ngql_string(self):
        self.assertEqual(ngql_string(None), "NULL")
        self.assertEqual(ngql_string(True), "true")
        self.assertEqual(ngql_string(5), "5")
        self.assertEqual(ngql_string('Hii "hiiiiiiii"'), '"Hii \\"hiiiiiiii\\""')

    def test_vid(self):
        self.assertEqual(vid("email", "abc"), "email:abc")

    def test_record_vid(self):
        self.assertEqual(record_vid("ORDERS", "123"), "record:orders:123")

    def test_identifier_type(self):
        self.assertEqual(identifier_type("email:a:b:c"), ["email", "a:b:c"])

    def test_parse_date(self):
        self.assertIsNotNone(parse_date("2026-01-01T00:00:00"))
        self.assertIsNone(parse_date(None))
        self.assertIsNone(parse_date("Date"))

class RowToNgqlTests(unittest.TestCase):
    def row_to_ngql_test(self):
        schema_cols = load_schema_cols()
        row = GraphRow.from_db_row(build_row("r1", email="a@gmail.com", phone="12345"), schema_cols)
        statements = row_to_ngql(row)
        joined = "\n".join(statements)
        self.assertIn("INSERT VERTEX", joined)
        self.assertIn("has_email", joined)
        self.assertIn("has_phone", joined)
        self.assertNotIn("has_maid", joined)

class BelongsToIdentityTests(unittest.TestCase):
    def setUp(self):
        self.schema_cols = load_schema_cols()
        self.nebula = FakeNebulaClient()

    def sync(self, raw_rows, max_identifiers=50, remap_type=3, phone_gap=True):
        rows = [GraphRow.from_db_row(row, self.schema_cols) for row in raw_rows]
        cluster_map, transaction_dates, _ = cluster_identifiers(rows, {}, phone_gap, self.schema_cols)
        all_identifiers = distinct_identifiers(cluster_map)
        identifier_identity_map = {}
        for identifier in all_identifiers:
            current = None
            for identity_vid, props in self.nebula.graph.out_edges.get(identifier, {}).get("belongs_to", {}).items():
                if props.get("end_date", "") == "":
                    current = identity_vid
            if current:
                identifier_identity_map[identifier] = current
        if not phone_gap:
            transaction_dates = None
        statements, invalid_declare, _ = belongs_to_identity(identifier_identity_map, cluster_map, transaction_dates, max_identifiers, remap_type, self.schema_cols, self.nebula)
        for row in rows:
            self.nebula.execute_many(row_to_ngql(row))
        self.nebula.execute_many(statements)
        return statements, invalid_declare
    def active_identity(self, identifier_vid):
        for identity_vid, props in self.nebula.graph.out_edges.get(identifier_vid, {}).get("belongs_to", {}).items():
            if props.get("end_date", "") == "":
                return identity_vid
        return None

    def test_email_merge(self):
        self.sync([build_row("r1", email="a@gmail.com"), build_row("r2", email="a@gmail.com")])
        email_vid = vid("email", sha256_text("a@gmail.com"))
        self.assertIsNotNone(self.active_identity(email_vid))

    def test_phone_gap(self):
        self.sync([build_row("r1", phone="12345678", transaction_date="2023-01-01T00:00:00")])
        phone_vid = vid("phone", sha256_text("12345678"))
        identity1 = self.active_identity(phone_vid)
        self.assertIsNotNone(identity1)
        self.sync([build_row("r2", phone="12345678", transaction_date="2025-08-08T00:00:00")])
        identity2 = self.active_identity(phone_vid)
        self.assertIsNotNone(identity2)
        self.assertNotEqual(identity1, identity2)

    def test_active_edge_date(self):
        self.sync([build_row("r1", phone="12345678", transaction_date="2023-01-01T00:00:00")])
        self.sync([build_row("r2", phone="12345678", transaction_date="2025-08-08T00:00:00")])
        phone_vid = vid("phone", sha256_text("12345678"))
        active_edges = []
        for identity, props in self.nebula.graph.out_edges[phone_vid]["belongs_to"].items():
            if props.get("end_date", "") == "":
                active_edges.append(identity)
        self.assertEqual(len(active_edges), 1)

    def test_supernode_threshold(self):
        self.sync([build_row(f"r{i}", email="a@gmail.com", phone=f"1234567{i}", screen_width=str(1000 + i * 50), city=f"city{i}") for i in range(4)], max_identifiers=3)
        statements, invalid_declare = self.sync([build_row(f"rb{i}", email="a@gmail.com", phone=f"12345678{i}", screen_width=str(2000 * i * 50), city=f"cityy{i}") for i in range(3)], max_identifiers=3, remap_type=3)
        self.assertTrue(any(pair[1] == sha256_text("a@gmail.com") for pair in invalid_declare))
        self.assertIsInstance(statements, list)

class NgqlStatementsTests(unittest.TestCase):
    def test_insert_vertex(self):
        statement = insert_vertex("email", "email:a", {"value": "a"})
        self.assertEqual(statement, 'INSERT VERTEX `email`(value) VALUES "email:a":("a")')

    def test_insert_multiTag_vertex(self):
        statement = insert_vertex(["record", "fg_hash"], "r:1", {"record": {"a": "1"}, "fg_hash": {"b": "2"}})
        self.assertIn('`record`(a)', statement)
        self.assertIn('`fg_hash`(b)', statement)
        self.assertIn('VALUES "r:1":("1", "2")', statement)

    def test_insert_edge(self):
        statement = insert_edge("has_email", "r:1", "email:a")
        self.assertEqual(statement, 'INSERT EDGE `has_email`() VALUES "r:1"->"email:a":()')

    def test_insert_edge_props(self):
        statement = insert_edge("belongs_to", "email:a", "uid:1", {"start_date": "2024-01-01T00:00:00", "end_date": ""})
        self.assertIn('start_date, end_date', statement)
        self.assertIn('"2024-01-01T00:00:00", ""', statement)

    def test_update_vertex(self):
        statement = update_vertex("uid:1", "identity_no", {"deprecated": True})
        self.assertEqual(statement, 'UPDATE VERTEX "uid:1" SET identity_no.deprecated = true')
    def test_update_edge(self):
        statement = update_edge("belongs_to", "email:a", "uid:1", {"end_date": "2024-01-01T00:00:00"})
        self.assertEqual(statement, 'UPDATE EDGE ON belongs_to "email:a"->"uid:1" SET end_date = "2024-01-01T00:00:00"')

class GraphRowFromdbTests(unittest.TestCase):
    def setUp(self):
        self.schema_cols = load_schema_cols()

    def test_result(self):
        row = GraphRow.from_db_row(build_row("r1", email="a@gmail.com", phone="12345678"), self.schema_cols)
        self.assertIsNotNone(row.identifiers["email"])
        self.assertIsNotNone(row.identifiers["phone"])
        self.assertIsNotNone(row.signals["device_props"])
        self.assertIsNotNone(row.signals["ip_loc"])
        self.assertIsNone(row.identifiers["maid"])

    def test_missing_signals(self):
        raw = build_row("r1", email="a@gmail.com")
        raw["ip_country"] = None
        raw["city"] = None
        raw["language"] = None
        row = GraphRow.from_db_row(raw, self.schema_cols)
        self.assertIsNone(row.signals["ip_loc"])

    def test_vertexid(self):
        row = GraphRow.from_db_row(build_row("r1", email="a@gmail.com"), self.schema_cols)
        self.assertEqual(row.vertex_id, "record:orders:r1")


if __name__ == "__main__":
    unittest.main()