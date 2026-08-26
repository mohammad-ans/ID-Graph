from __future__ import annotations
import sys, yaml, hashlib
import unittest
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent / "main"
DEMO_DIR = Path(__file__).resolve().parent.parent / "demo"
sys.path.insert(0, str(MAIN_DIR))
sys.path.insert(0, str(DEMO_DIR))

from demo.nebula_f import FakeNebulaClient
from main.batch_id_union import cluster_identifiers
from main.graph_model import GraphRow, normalize_token, normalize_loc, sha256_text, is_valid_maid, ngql_string, vid, record_vid, identifier_type, parse_date, row_to_ngql

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