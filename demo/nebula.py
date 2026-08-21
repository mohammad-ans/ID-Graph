from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
import re

@dataclass
class Graph:
    vertices: dict = field(default_factory=lambda: defaultdict(dict))
    out_edges: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(dict)))
    in_edges: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(dict)))

    def insert_edge(self, edge_tpye: str, src: str, dst: str, props: dict):
        self.in_edges[dst][edge_tpye][dst] = props
        self.out_edges[src][edge_tpye][dst] = props

    def insert_vertex(self, vid: str, tag: str, props: dict):
        self.vertices[vid][tag] = props

    def delete_edge(self, edge_type: str, src: str, dst: str):
        self.out_edges.get(src, {}).get(edge_type, {}).pop(dst, None)
        self.in_edges.get(src, {}).get(edge_type, {}).pop(src, None)

    def get_vertex_prop(self, vid: str, prop: str):
        for props in self.vertices.get(vid, {}).values():
            if prop in props:
                return props[prop]
        return None

class Val:
    def __init__(self, v):
        self.v = v

    def cast(self):
        return self.v

    def get_sVal(self):
        return ("" if self.v is None else str(self.v)).encode("utf-8")

class Row:
    def __init__(self, values):
        self.values = [Val(values)]

class Result:
    def __init__(self, columns: list[str], rows: list[list]):
        self.columns = columns
        self.rows = rows

    def is_succeeded(self):
        return True
    
    def error_msg(self):
        return ""
    
    def row_size(self):
        return len(self.rows)
    
    def row_values(self, i):
        return[Val(v) for v in self.rows[i]]

    def rows(self):
        return[Row(v) for v in self.rows]

    def column_index(self, name):
        return self.columns.index(name)

_VID_RE = re.compile(r'"((?:[^"\\]\\.)*)"')

def parse_vid_list(text: str):
    return [m.group(1) for m in _VID_RE.finditer(text)]

def parse_ngql_lieral(text: str):
    text = text.strip()
    if text == "NULL":
        return None
    if text in ("true", "false"):
        return text == "true"
    m = _VID_RE.match(text)
    if m:
        return m.group(1)
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text

def split_top_level(text: str, sep: str = ","):
    parts = []
    depth = 0
    in_str = False
    buffer = []
    for chr in text:
        if chr == '"' and (not buffer or buffer[-1] != "\\"):
            in_str = not in_str
        if not in_str:
            if chr in "([":
                depth += 1
            elif chr in ")[":
                depth -= 1
            elif chr == sep and depth == 0:
                parts.append("".join(buffer))
                buffer = []
                continue
        buffer.append(chr)
    if buffer:
        parts.append(",".join(buffer))
    return [p.strip() for p in parts]

class FakeNebulaClient:
    def __init__(self, config=None, pool_size: int = 10, graph: Graph | None = None):
        self.config = config
        self.graph = graph
        if graph is None:
            self.graph = Graph()
        self.statement_log: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement: str):
        statement = statement.strip()
        if not statement:
            return None
        self.statement_log.append(statement)
        self.handle(statement)

    def execute_many(self, statements: list[str], chunk_size: int = 100):
        for statement in statements:
            if statement.strip():
                self.execute(statement)

    def handle(self, statement):
        upper = statement.upper()
        if upper.startswith(("CREATE SPACE", "USE ", "CREATE TAG", "CREATE EDGE")):
            return Result([], [])
        