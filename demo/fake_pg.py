import json

class Cursor:
    def __init__(self, table: list[dict]):
        self.table = table
        self.result: list[tuple] = []
        self.rowcount = 0

    def __enter__(self, *exc):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False
    def execute(self, sql: str, params: tuple = ()):
        sql_norm = " ".join(sql.split())
        if sql_norm.startswith("UPDATE"):
            record_a, record_b = params[1], params[2]
            decision = params[0]
            updated = 0
            for row in self.table:
                if {row["record_id_a"], row["record_id_b"]} == {record_a, record_b}:
                    row["decision"] = decision
                    row["decided_at"] = "now"
                    updated += 1
                self.rowcount = updated
                return
        if "WHERE decision IS NULL" in sql_norm and "ORDER BY" in sql_norm:
            limit = params[0]
            undecided = [row for row in self.table if row.get("decision") is None]
            undecided.sort(key=lambda row: abs(row["score"] - 0.5))
            self.result = [(row["record_id_a"], row["record_id_b"], row["score"], row["features"]) for row in undecided[:limit]]
            return
        if "WHERE decision IS NOT NULL" in sql_norm:
            self.result = [(json.dumps(row["features"]), row["decision"]) for row in self.table if row.get("decision") is not None]
            return
    def fetchall(self):
        return self.result
    def fetchone(self):
        return self.result[0] if self.result else None

class ReviewQueue:
    def __init__(self):
        self.table = []

    def cursor(self):
        return Cursor(self.table)

    def commit(self):
        pass

    def insert_candidate(self, a, b, score, features):
        self.table.append({"record_id_a": a, "record_id_b": b, "score": score, "features": features, "decision": None, "decided_at": None})