from __future__ import annotations
import unittest
from pathlib import Path
import sys

DEMO_DIR = Path(__file__).parent.parent / "demo"
sys.path.insert(0, str(DEMO_DIR))

from nebula_f import FakeNebulaClient

class DdlTests(unittest.TestCase):
    def test_ddl_statements(self):
        nebula = FakeNebulaClient()
        for statement in ['CREATE SPACE audience_graph_test', 'USE audience_graph_test', 'CREATE TAG identity_no()', 'CREATE EDGE belongs_to(start_date string, end_date string)']:
            result = nebula.execute(statement)
            self.assertTrue(result.is_succeeded())
            self.assertEqual(result.row_size(), 0)

class MutationTests(unittest.TestCase):
    def setUp(self):
        self.nebula = FakeNebulaClient()

    def test_insert_vertex(self):
        self.nebula.execute('INSERT VERTEX `email`(value) VALUES "email:abc":("abc")')
        self.assertEqual(self.nebula.graph.get_vertex_prop("email:abc", "value"), "abc")

    def test_insert_vertex_multi(self):
        self.nebula.execute('INSERT VERTEX `record`(a, b) `fg_hash`(c) VALUES "r1":("1", "2", "3")')
        self.assertEqual(self.nebula.graph.vertices["r1"]["record"], {"a": "1", "b": "2"})
        self.assertEqual(self.nebula.graph.vertices["r1"]["fg_hash"], {"c": "3"})

    def test_insert_vertex_parse_typed_literal(self):
        self.nebula.execute('INSERT VERTEX `identity_no`(deprecated, count, ratio) ' 'VALUES "id1":(true, 5, 1.5)')
        props = self.nebula.graph.vertices["id1"]["identity_no"]
        self.assertIs(props["deprecated"], True)
        self.assertEqual(props["count"], 5)
        self.assertEqual(props["ratio"], 1.5)

    def test_insert_edge(self):
        self.nebula.execute('INSERT EDGE `has_email`() VALUES "r1"->"email:a":()')
        self.assertEqual(self.nebula.graph.out_edges["r1"]["has_email"]["email:a"], {})

    def test_insert_edge_props(self):
        self.nebula.execute('INSERT EDGE `belongs_to`(start_date, end_date) VALUES "email:a"->"id1":("2026-01-01T00:00:00", "")')
        props = self.nebula.graph.out_edges["email:a"]["belongs_to"]["id1"]
        self.assertEqual(props["start_date"], "2026-01-01T00:00:00")
        self.assertEqual(props["end_date"], "")
        self.assertEqual(self.nebula.graph.in_edges["id1"]["belongs_to"]["email:a"], props)

    def test_update_edge(self):
        self.nebula.execute('INSERT EDGE `belongs_to`(start_date, end_date) VALUES "email:a"->"id1":("2026-01-01T00:00:00", "")')
        self.nebula.execute('UPDATE EDGE ON belongs_to "email:a"->"id1" SET end_date = "2026-06-01T00:00:00"')
        props = self.nebula.graph.out_edges["email:a"]["belongs_to"]["id1"]
        self.assertEqual(props["end_date"], "2026-06-01T00:00:00")
        self.assertEqual(props["start_date"], "2026-01-01T00:00:00")

    def test_update_vertex(self):
        self.nebula.execute('INSERT VERTEX `identity_no`() VALUES "id1"->"email:a"()')
        self.nebula.execute('UPDATE VERTEX "id1" SET identity_no.deprecated = true, identity_no.merged_into = "id2"')
        props = self.nebula.graph.vertices["id1"]["identity_no"]
        self.assertIs(props["deprecated"], True)
        self.assertEqual(props["merged_into"], "id2")

    def test_delete_edge(self):
        self.nebula.execute('INSERT EDGE `has_email`() VALUES "r1"->"email:a":()')
        self.nebula.execute('DELETE EDGE has_email "r1"->"email:a"')
        self.assertNotIn("email:a", self.nebula.graph.out_edges.get("r1", {}).get("has_email", {}))
        self.assertNotIn("r1", self.nebula.graph.in_edges.get("email:a", {}).get("has_email", {}))