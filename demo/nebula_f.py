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
        self.in_edges[dst][edge_tpye][src] = props
        self.out_edges[src][edge_tpye][dst] = props

    def insert_vertex(self, vid: str, tag: str, props: dict):
        self.vertices[vid][tag] = props

    def delete_edge(self, edge_type: str, src: str, dst: str):
        self.out_edges.get(src, {}).get(edge_type, {}).pop(dst, None)
        self.in_edges.get(dst, {}).get(edge_type, {}).pop(src, None)

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
        self._rows = rows

    def is_succeeded(self):
        return True
    
    def error_msg(self):
        return ""
    
    def row_size(self):
        return len(self._rows)
    
    def row_values(self, i):
        return[Val(v) for v in self._rows[i]]

    def rows(self):
        return[Row(v) for v in self._rows]

    def column_index(self, name):
        return self.columns.index(name)

_VID_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')

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
        return self.handle(statement)

    def execute_many(self, statements: list[str], chunk_size: int = 100):
        for statement in statements:
            if statement.strip():
                self.execute(statement)

    def handle(self, statement):
        upper = statement.upper()
        if upper.startswith(("CREATE SPACE", "USE ", "CREATE TAG", "CREATE EDGE")):
            return Result([], [])
        if upper.startswith("INSERT VERTEX"):
            return self.insert_vertex(statement)
        if upper.startswith("INSERT EDGE"):
            return self.insert_edge(statement)
        if upper.startswith("UPDATE EDGE"):
            return self.update_edge(statement)
        if upper.startswith("UPDATE VERTEX"):
            return self.update_vertex(statement)
        if upper.startswith("DELETE EDGE"):
            return self.delete_edge(statement)
        if upper.startswith("GO FROM"):
            return self.go(statement)
        raise NotImplementedError(f"Statement not found")

    def insert_vertex(self, statement):
        body = statement[len("INSERT VERTEX"):].strip()
        head, values_part = body.split(" VALUES ", 1)
        tag_specs = re.findall(r'`?(\w+)`?\(([^)]*)\)', head)
        vid_match = _VID_RE.match(values_part.strip())
        vid = vid_match.group(1)
        rest = values_part.strip()[vid_match.end():].lstrip(":").strip()
        if rest.startswith("(") and rest.endswith(")"):
            rest = rest[1:-1]
        all_values = split_top_level(rest) if rest.strip() else []
        offset = 0
        for tag, cols in tag_specs:
            col_names = [c.strip() for c in cols.split(",")] if cols.strip() else []
            n = len(col_names)
            vals = all_values[offset: offset + n]
            offset += n
            props = {c: parse_ngql_lieral(v) for c, v in zip(col_names, vals)}
            self.graph.insert_vertex(vid, tag, props)
        return Result([], [])

    def insert_edge(self, statement):
        m = re.match(r'INSERT EDGE `?(\w+)`?\(([^)]*)\) VALUES\s+(.+)', statement, re.IGNORECASE | re.DOTALL)
        edge_type = m.group(1)
        cols = m.group(2)
        values_part = m.group(3)
        vids = parse_vid_list(values_part)
        src = vids[0]
        dest = vids[1]
        vals_match = re.search(r':\(([^)]*)\)', values_part)
        col_names = [c.strip() for c in cols.split(",")] if cols.strip() else []
        val_items = []
        if vals_match and vals_match.group(1).strip():
            val_items = split_top_level(vals_match.group(1))
        props = {c: parse_ngql_lieral(v) for c, v in zip(col_names, val_items)}
        self.graph.insert_edge(edge_type, src, dest, props)
        return Result([], [])

    def update_edge(self, statement):
        m = re.match(r'UPDATE EDGE ON (\w+)\s+(.+?)\s+SET\s+(.+)', statement, re.IGNORECASE | re.DOTALL)
        edge_type = m.group(1)
        vid_part = m.group(2)
        set_part = m.group(3)
        src, dst = parse_vid_list(vid_part)
        props = self.graph.out_edges.get(src, {}).get(edge_type, {}).get(dst, {})
        for assignment in split_top_level(set_part):
            col, val = assignment.split("=", 1)
            props[col.strip()] = parse_ngql_lieral(val.strip())
        self.graph.insert_edge(edge_type, src, dst, props)

    def update_vertex(self, statement):
        m = re.match(r'UPDATE VERTEX\s+(.+?)SET\s(.+)', statement, re.IGNORECASE | re.DOTALL)
        vid = _VID_RE.match(m.group(1).strip()).group(1)
        set_part = m.group(2)
        for assignment in split_top_level(set_part):
            #colFull is tag.col
            colFull, val = assignment.split("=", 1)
            tag, col = colFull.strip().split(".", 1)
            self.graph.vertices[vid].setdefault(tag, {})[col] = parse_ngql_lieral(val.strip())
        return Result([], [])

    def delete_edge(self, statement):
        m = re.match(r'DELETE EDGE\s+(\w+)\s+(.+)', statement, re.IGNORECASE)
        edge_type = m.group(1)
        vid_part = m.group(2)
        src, dst = parse_vid_list(vid_part)
        self.graph.delete_edge(edge_type, src, dst)
        return Result([], [])

    def go(self, statement: str, carry: list[dict] | None = None):
        stage, _, piped = statement.partition("|")
        stage = stage.strip()
        m = re.match(r'GO FROM\s+(?P<from>.+?)\s+OVER\s+(?P<edges>[\w,]+)'
                     r'(?P<reversely>\s+REVERSELY)?'
                     r'(?:\s+WHERE\s+(?P<where>.+?))?'
                     '\s+YIELD\s+(?P<yield>.+)$', stage, re.IGNORECASE | re.DOTALL)
        if not m:
            raise NotImplementedError(f"Error in GO query")
        from_clause = m.group("from").strip()
        edge_types = [e.strip() for e in m.group("edges").split(",")]
        reversely = bool(m.group("reversely"))
        not_end_date = bool(m.group("where")) and "end_date" in m.group("where")
        yield_fields = split_top_level(m.group("yield"))

        from_pairs: list[tuple[str, dict | None]]
        if from_clause.startswith("$-."):
            col = from_clause[len("$-."):].strip()
            from_pairs = [(row[col], row) for row in (carry or []) if row.get(col) is not None]
        else:
            from_pairs = [(v, None) for v in parse_vid_list(from_clause)]
        out_rows = []
        for fid, parent_row in from_pairs:
            for et in edge_types:
                neighbor_map = (self.graph.in_edges.get(fid, {})).get(et, {})
                if not reversely:
                    neighbor_map = self.graph.out_edges.get(fid, {}).get(et, {})
                for landed_vid, edge_props in neighbor_map.items():
                    if not_end_date and edge_props.get("end_date", "") != "":
                        continue
                    src, dest = (fid, landed_vid)
                    if reversely:
                        src, dest = (landed_vid, fid)
                    row = {"__landed__": landed_vid, "__from__": fid, "__parent__": parent_row}
                    for field_expr in yield_fields:
                        expr, _, alias = field_expr.strip().rpartition(" AS ")
                        expr = expr.strip() or field_expr.strip()
                        alias = alias.strip() or expr
                        if expr.lower() == "src(edge)":
                            row[alias] = src
                        elif expr.lower() == "dst(edge)":
                            row[alias] = dest
                        elif expr.startswith("properties($$)."):
                            prop = expr[len("properties($$)."):]
                            row[alias] = self.graph.get_vertex_prop(landed_vid, prop)
                        elif expr.startswith("$-."):
                            col = expr[len("$-."):]
                            row[alias] = parent_row.get(col) if parent_row else None
                        else:
                            raise NotImplementedError(f"YIELD field error: {field_expr}")
                    out_rows.append(row)
        if piped.strip():
            return self.go(piped.strip(), carry=out_rows)
        columns = [c for c in out_rows[0].keys() if not c.startswith("__")] if out_rows else [f.strip().rpartition("  AS  ")[-1].strip() for f in yield_fields]
        rows = [[r.get(c) for c in columns] for r in out_rows]
        return Result(columns, rows)