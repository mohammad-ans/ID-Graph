from logging import getLogger
from dataclasses import dataclass, field
from graph_model import GraphRow
import datetime
import hashlib
from nebula_client import NebulaClient

logger = getLogger(__name__)


class InvalidIdentifiers:
    invalid_identifiers : dict[str, dict[str, int]]
    def __init__(self):
        self.invalid_identifiers = {"email" : {}, "phone" : {}}

    def invalid_relative_newD(self, batch_data : list[GraphRow]):
        MAX_IDENTIFIER_TRANSACTIONS = len(batch_data) / 20
        freq_map = {}
        for row in batch_data:
            for identifier_type, identifier in row.identifiers.items():
                if identifier is not None:
                    freq_map[identifier] = freq_map.get(identifier, 0) + 1
                    if freq_map[identifier] > MAX_IDENTIFIER_TRANSACTIONS:
                        self.invalid_identifiers[identifier_type][identifier] = freq_map[identifier]

    @staticmethod
    def hash_sha256_hex(identifier : str):
        return hashlib.sha256(identifier.strip().lower().encode("utf-8")).hexdigest()

    def hashed_static_identifiers(self, static_identifiers: dict[str, set[str]]):
        for identifier_type in static_identifiers:
            for identifier in static_identifiers[identifier_type]:
                hashed_identifier = InvalidIdentifiers.hash_sha256_hex(identifier)
                self.invalid_identifiers[identifier_type][hashed_identifier] = -1
    def add_static_identifiers(self, static_identifiers: dict[str, set[str]]):
        for identifier_type in static_identifiers:
            for identifier in static_identifiers[identifier_type]:
                self.invalid_identifiers[identifier_type][identifier] = -1

    def invalid_identifiers_graphdb(self, nebula : NebulaClient):
        pass



@dataclass
class IdentityGroup:
    root : str
    identifiers : set[str] = field(default_factory=set)


class UnionFind:
    def __init__(self):
        self.parent : dict[str, str] = {}
        self._size : dict[str, int] = {}

    def ensureRoot(self, x):
        if x not in self.parent:
            self.parent[x] = x
            self._size[x] = 1

    def find(self, x):
        self.ensureRoot(x)
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]
    def union(self, x, y):
        rootX = self.find(x)
        rootY = self.find(y)

        if rootX == rootY:
            return
        if self._size[rootX] < self._size[rootY]:
            self.parent[rootX] = rootY
            self._size[rootY] += self._size[rootX]
        else:
            self.parent[rootY] = rootX
            self._size[rootX] += self._size[rootY]

def valid_identifiers(row : GraphRow, invalid_identifiers : dict[str, dict[str, int]], schema_cols : dict) -> list[str]:
    candidates = []
    for identifier in schema_cols["identifiers"]:
        name = identifier["name"]
        candidates.append((name, row.identifiers.get(name, None)))
    identifiers = []
    for id_type, identifier in candidates:
        if (not identifier) or identifier in invalid_identifiers[id_type]:
            # logger.info(
            #     f"Invalid identifier {identifier}"
            #     )
            continue
        identifiers.append(f"{id_type}:{identifier}")
    return identifiers

def parse_date(date : str):
    try:
        return datetime.datetime.fromisoformat(date)
    except ValueError:
        return None

def cluster_identifiers(rows : list[GraphRow], static_invalid_identifiers : dict[str, set[str]], phone_gap: bool, schema_cols: dict):

    invalid_identifiers = InvalidIdentifiers()
    invalid_identifiers.add_static_identifiers(static_invalid_identifiers)
    invalid_identifiers.invalid_relative_newD(rows)
    logger.info(
        f"Fetched invalid identifiers... Total emails: {len(invalid_identifiers.invalid_identifiers["email"])}\nTotal phone records: {len(invalid_identifiers.invalid_identifiers["phone"])}"
    )

    uf = UnionFind()

    unresolvable = []
    transaction_dates = {}
    for row in rows:
        identifiers = valid_identifiers(row, invalid_identifiers.invalid_identifiers, schema_cols)
        if not identifiers:
            unresolvable.append(row)
            continue
        if phone_gap:
            date = parse_date(row.transaction_date)
            if date is not None:
                if identifiers[0] in transaction_dates:
                    transaction_dates[identifiers[0]] = min(transaction_dates[identifiers[0]], date)
                else:
                    transaction_dates[identifiers[0]] = date
        if(len(identifiers) == 1):
            uf.find(identifiers[0])

        for i in range(1, len(identifiers)):
            if phone_gap:
                if date is not None:
                    if identifiers[i] in transaction_dates:
                        transaction_dates[identifiers[i]] = min(transaction_dates[identifiers[i]], date)
                    else:
                        transaction_dates[identifiers[i]] = date
            uf.union(identifiers[0], identifiers[i])

    cluster_map : dict[str , IdentityGroup] = {}

    for vid in uf.parent:
        root = uf.find(vid)
        if root not in cluster_map:
            cluster_map[root] = IdentityGroup(root = root)
        cluster_map[root].identifiers.add(vid)

    logger.info(
        f"Grouped identifiers from {len(rows)}"
        f"into {len(cluster_map)} idependent identifier clusters"
    )

    return cluster_map, transaction_dates

def distinct_identifiers(cluster_map : dict[str , IdentityGroup]) -> list[str]:
    identifiers = []
    for group in cluster_map:
        identifiers.extend(cluster_map[group].identifiers)
    return identifiers
    