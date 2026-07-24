from __future__ import annotations
from uuid import uuid4
import hashlib
import re
from dataclasses import dataclass
from collections import defaultdict
import datetime
from decimal import Decimal
from typing import Iterable
from nebula_client import NebulaClient
from cluster_union_strict import cluster_identifiers_strict
_VID_SAFE_RE = re.compile(r"[^A-Za-z0-9_.:@|-]+")
_LOC_SAFE_RE = r"[^a-z0-9]+"

# Sentinel MAID values some SDKs send when a user has disabled ad tracking.
# These are NOT real device identifiers -- letting them through would link
# every privacy-conscious user on the same OS into one giant false identity.
_DEVICE_SENTINELS = frozenset({
    "00000000-0000-0000-0000-000000000000",  # iOS / Android disabled-tracking sentinel
    "00000000000000000000000000000000",
})
MAX_GAP_PHONE = 720

def clean_text(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def normalize_token(value) -> str | None:
    cleaned = clean_text(value)
    if not cleaned:
        return None
    cleaned = cleaned.lower()
    return _VID_SAFE_RE.sub("_", cleaned)

def normalize_loc(value : str) -> str | None:
    value = clean_text(value)
    if value is None:
        return ""
    value = value.lower()
    return re.sub(_LOC_SAFE_RE, "", value)

def sha256_text(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def is_valid_maid(value: str | None) -> bool:
    """
    Guards against linking on a MAID that isn't a real device identifier.
    Returns False for null/empty values and known sentinel placeholders.
    """
    if not value:
        return False
    cleaned = value.strip()
    if not cleaned:
        return False
    return cleaned not in _DEVICE_SENTINELS


def ngql_string(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        value = value.isoformat()
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def vid(prefix: str, value: str) -> str:
    return f"{prefix}:{value}"


def record_vid(table_name: str, record_id: str) -> str:
    return vid("record", f"{normalize_token(table_name)}:{record_id}")

def process_user_agent(user_agent : str):
    pass

@dataclass(frozen=True)
class GraphRow:
    record_id: str
    identifiers: dict[str, str | None]
    signals: dict[str, str | None]
    attributes: dict[str, str | None]

    # standardized_table: str
    # record_id: str
    # provider_id: str | None
    # source_table: str | None
    # hashed_email: str | None
    # hashed_phone: str | None
    # maid: str | None
    # country: str | None
    # user_agent: str | None
    # merchant_name: str | None
    # merchant_url: str | None
    # transaction_id: str | None
    # transaction_date: str | None
    # primary_category: str | None
    # secondary_category: str | None

    @classmethod
    def from_db_row(cls, row: dict, config) -> GraphRow:
        identifiers = {}
        for spec in config["identifiers"]:
            value = clean_text(row.get(spec["column"]))
            if value is not None and spec["pre_hashed"]:
                value = sha256_text(value)
            identifiers[spec["name"]] = value
        signals = {}
        for group in config["signal_groups"]:
            parts = [normalize_token(row.get(c)) for c in group["columns"]]
            combined = "".join(parts)
            signals[group["name"]] = sha256_text(combined) if combined else None

        attributes = {c: clean_text(row.get(c)) for c in config["passthrough"] }

        return cls(record_id=clean_text(row.get(config["record_id"][0])), identifiers=identifiers, signals=signals, attributes=attributes)
        

    @property
    def vertex_id(self) -> str:
        source_table = self.attributes.get("source_table", "Unknown")
        if source_table == None:
            source_table = "Unknown"
        return record_vid(source_table, self.record_id)


def insert_vertex(tags: str | list[str], vertex_id: str, props: dict[str, str] | dict[str, dict[str, str]]) -> str:
    if isinstance(tags, list):
        insert_query = f'INSERT VERTEX '
        values_grps = []
        for tag in tags:
            columns = ", ".join(props[tag].keys())
            values_grps.append(f'{ ", ".join(ngql_string(value) for value in props[tag].values()) }')
            insert_query += f'`{tag}`({columns}), '
        insert_query = insert_query.strip(", ") + f' VALUES {ngql_string(vertex_id)}:(' + f'{", ".join(values_grps)}'  + ')'
        return insert_query
    
    columns = ", ".join(props.keys())
    values = ", ".join(ngql_string(value) for value in props.values())
    return f"INSERT VERTEX `{tags}`({columns}) VALUES {ngql_string(vertex_id)}:({values})"


def insert_edge(edge: str, src: str, dst: str, props: dict | None = None) -> str:
    props = props or {}
    if props:
        columns = ", ".join(props.keys())
        values = ", ".join(ngql_string(value) for value in props.values())
        return f"INSERT EDGE `{edge}`({columns}) VALUES {ngql_string(src)}->{ngql_string(dst)}:({values})"
    return f"INSERT EDGE `{edge}`() VALUES {ngql_string(src)}->{ngql_string(dst)}:()"

def delete_edge(edge: str, src: str, dst: str) -> str:
    return f"DELETE EDGE {edge} {ngql_string(src)}->{ngql_string(dst)}" 

def update_edge(edge : str, src : str, dst : str, props : dict) -> str:
    set_props = ", ".join([f'{col} = {ngql_string(val)}' for col, val in props.items()])
    return f'UPDATE EDGE ON {edge} {ngql_string(src)}->{ngql_string(dst)} SET {set_props}'

def update_vertex(vertex_id : str, tag : str, properties : dict[str, str]):
    update_query =  f'UPDATE VERTEX {ngql_string(vertex_id)} SET '
    for column, value in properties.items():
        update_query += f'{tag}.{column} = {ngql_string(value)}, '
    update_query = update_query.strip(", ")
    return update_query


def row_to_ngql(row: GraphRow) -> list[str]:
    """
    Identity resolution uses email, phone, and maid ONLY -- those are the
    edges to traverse when asking "who is this." country and merchant are
    also vertices (so "everyone who transacted in Vietnam" or "everyone who
    shopped at Acme" is a direct traversal), but they are filtering/
    analytical edges, not identity-linking ones: two unrelated people
    sharing a country or merchant does not make them the same identity.
    source_table stays a plain property -- it's bookkeeping, not something
    you'd ever traverse from.
    """
    record_id = row.vertex_id
    statements = [
        insert_vertex(
            ["record", "fg_hash"],
            record_id,
            {
                "record": row.attributes,
                "fg_hash": row.signals
            },
        )
    ]


    # country = normalize_token(row.country)
    # if country:
    #     country_id = vid("country", country.upper())
    #     statements.append(insert_vertex("country", country_id, {"code": row.country.upper()}))
    #     statements.append(insert_edge("in_country", record_id, country_id))

    # merchant = normalize_token(row.merchant_name)
    # if merchant:
    #     merchant_id = vid("merchant", merchant)
    #     statements.append(
    #         insert_vertex("merchant", merchant_id, {"name": row.merchant_name, "url": row.merchant_url})
    #     )
    #     statements.append(insert_edge("transacted_with", record_id, merchant_id))

    for id_type, identifier in row.identifiers.items():
        if identifier:
            vertex_id = vid(id_type, identifier)
            statements.append(insert_vertex(id_type, vertex_id,{"value" : identifier}))
            statements.append(insert_edge(f'has_{id_type}', record_id, vertex_id))
    return statements

def generate_identitiy_no():
    return uuid4().hex

def add_identity(identifiers : set[str]) -> list[str]:
    identity = generate_identitiy_no()
    identity_id = vid("uid", identity)
    statements = [
        insert_vertex("identity_no", identity_id, {})
        ]
    statements.extend(attach_identifiers(identifiers, identity_id))
    return statements, identity_id
    

def attach_identifiers(identifiers : set[str] | list[str], identity_id : str) -> list[str]:
    statements = []
    today = datetime.datetime.now().isoformat()
    for identifier in identifiers:
        statements.append(insert_edge("belongs_to", identifier, identity_id, {"start_date" : today, "end_date" : ""}))
    return statements

def mergeIdentities(identity_list : set[str], nebula : NebulaClient) -> list[str]:
    insertion_statments = []
    update_statements = []
    identities_edges = {}
    today = datetime.datetime.now().isoformat()
    canonical = None
    total_identifiers = 0
    for identity in identity_list:
        result = nebula.execute(
            f'GO FROM "{identity}"'
            f' OVER belongs_to REVERSELY WHERE properties(edge).end_date == ""'
            ' YIELD src(edge) AS identifier_vid'
        )
        identities_edges[identity] = []
        for row in result.rows():
            identities_edges[identity].append(row.values[0].get_sVal().decode("utf-8"))
        len_edges = len(identities_edges[identity])
        total_identifiers += len_edges
        canonical = identity if (canonical is None) or (len(identities_edges[canonical]) < len_edges) else canonical
    
    for identity in identities_edges:
        if identity != canonical:
            for identifier in identities_edges[identity]:
                insertion_statments.append(insert_edge("belongs_to", identifier, canonical, {"start_date" : today, "end_date" : ""}))
                update_statements.append(update_edge("belongs_to", identifier, identity, {"end_date" : today}))
            update_statements.append(
                update_vertex(identity, "identity_no", {
                    "deprecated" : True,
                    "merged_into" : canonical
                })
            )

    insertion_statments.extend(update_statements)
    return insertion_statments, canonical, total_identifiers
        
def identifier_type(combined : str):
    return combined.split(":", 1)

def parse_date(date : str):
    try:
        return datetime.datetime.fromisoformat(date)
    except ValueError:
        return None


def check_phone_gap(phone : str, p_date : datetime.datetime, nebula: NebulaClient):
    try:
        result = nebula.execute(
            f'GO FROM "{phone}" OVER has_phone REVERSELY '
            f'YIELD properties($$).transaction_date AS t_date'
            )
        dates = []
        for i in range(result.row_size()):
            value = result.row_values(i)[0].cast()
            if value is None:
                continue
            date = parse_date(value) if isinstance(value, str) else None
            if date:
                dates.append(date)
        if not dates:
            return False
        date = max(dates)
        return abs(date - p_date).days < MAX_GAP_PHONE
        
        
    except Exception as exc:
        return False

def rules(identity_matches : dict[str, list[str]], transaction_dates : dict[str, datetime.datetime] | None, nebula):
    valid_merges = set()
    for identity, identifiers in identity_matches.items():
        for identifier in identifiers:
            id_type, id_val = identifier_type(identifier)
            if id_type == "email":
                valid_merges.add(identity)
                break
            if id_type == "phone":
                if transaction_dates:
                    date = datetime.datetime.now()
                    if identifier in transaction_dates:
                        date = transaction_dates[identifier]
                    if check_phone_gap(identifier, date, nebula):
                        valid_merges.add(identity)
                        break
                else:
                    valid_merges.add(identity)

    return valid_merges
            


def belongs_to_identity(identifier_identity_map : dict[str, str], cluster_map: dict, transaction_dates : dict[str, datetime.datetime] | None, max_identifiers : int, remap_type : int, schema_cols : dict, nebula : NebulaClient):
    statements = []
    db_statements = []
    for component in cluster_map.values():
        identity_matches = {}
        new_identifiers = []
        total_identifiers = 0
        canonical_identity = None
        for identifier in component.identifiers:
            if identifier in identifier_identity_map:
                identity_matches.setdefault(identifier_identity_map[identifier], []).append(identifier)
            else:
                new_identifiers.append(identifier)

        valid_merges = rules(identity_matches, transaction_dates, nebula)
        if len(valid_merges) == 0:
            total_identifiers = len(component.identifiers)
            new_statements, canonical_identity = add_identity(component.identifiers)
            statements.extend(new_statements)
        elif len(valid_merges) == 1:
            total_identifiers = len(new_identifiers)
            canonical_identity = valid_merges.pop()
            results = nebula.execute(
                f'GO FROM "{canonical_identity}" OVER belongs_to REVERSELY WHERE properties(edge).end_date == "" YIELD src(edge) AS identifier_vid'
            )
            total_identifiers += results.row_size()
            statements.extend(attach_identifiers(new_identifiers, canonical_identity))
        else:
            new_statements, canonical_identity, total_identifiers = mergeIdentities(valid_merges, nebula)
            statements.extend(new_statements)
            statements.extend(attach_identifiers(new_identifiers, canonical_identity))
            total_identifiers += len(new_identifiers)
        
        if total_identifiers > max_identifiers:
            if schema_cols["signal_groups"] is None:
                # logger.info
                pass
            new_statements, new_db_statements = remap_identifiers_strict(canonical_identity, nebula, remap_type, schema_cols)
            statements.extend(new_statements)
            db_statements.extend(new_db_statements)
    return statements, db_statements

def remap_identifiers_strict(identity_vid : str, nebula : NebulaClient, remap_type : int, schema_cols : dict):
    statements = []
    db_statements = []
    result = cluster_identifiers_strict(identity_vid, nebula, schema_cols)
    if result == None:
        return statements, db_statements
    cluster_identifier, identifier_clusters, largest_cluster, identifier_count = result
    today = datetime.datetime.now().isoformat()
    if remap_type == 0 or remap_type == 1:
            
        for cluster in cluster_identifier:
            if cluster == largest_cluster:
                continue
            identity = vid("uid", generate_identitiy_no())
            statements.append(insert_vertex("identity_no", identity, {}))
            for identifier in cluster_identifier[cluster]:
                if len(identifier_clusters[identifier]) == 0:
                    continue
                if len(identifier_clusters[identifier]) == 1 and cluster in identifier_clusters[identifier]:
                    statements.append(insert_edge("belongs_to", identifier, identity, {"start_date" : today, "end_date" : ""}))
                else:
                    identifier_clusters[identifier].clear()

                statements.append(update_edge("belongs_to", identifier, identity_vid, {"end_date" : today}))


    elif remap_type == 2:

        for cluster in cluster_identifier:
            if cluster == largest_cluster:
                continue
            identity = vid("uid", generate_identitiy_no())
            statements.append(insert_vertex("identity_no", identity, {}))
            for identifier in cluster_identifier[cluster]:

                if len(identifier_clusters[identifier]) > 1:
                    max_identifier_cluster = max(identifier_clusters[identifier], key=lambda c : identifier_clusters[identifier][c])
                    identifier_clusters[identifier].clear()
                    identifier_clusters[identifier][max_identifier_cluster] = 1

                if len(identifier_clusters[identifier]) == 1 and cluster in identifier_clusters[identifier]:
                    statements.append(insert_edge("belongs_to", identifier, identity, {"start_date" : today, "end_date" : ""}))

                statements.append(update_edge("belongs_to", identifier, identity_vid, {"end_date" : today}))

    elif remap_type == 3:

        for cluster in cluster_identifier:
            if cluster == largest_cluster:
                continue
            identity = vid("uid", generate_identitiy_no())
            statements.append(insert_vertex("identity_no", identity, {}))

            for identifier in cluster_identifier[cluster]:
                if len(identifier_clusters[identifier]) == 0:
                    continue
                if len(identifier_clusters[identifier]) == 1:
                    statements.append(insert_edge("belongs_to", identifier, identity, {"start_date" : today, "end_date" : ""}))
                else:
                    identifier_clusters[identifier].clear()
                    db_statements.append(identifier_type(identifier))
                statements.append(update_edge("belongs_to", identifier, identity_vid, {"end_date" : today}))    

    return statements, db_statements
                
def rows_to_ngql(rows: Iterable[GraphRow]) -> str:
    statements: list[str] = []
    for row in rows:
        statements.extend(row_to_ngql(row))
    return ";\n".join(statements) + (";" if statements else "")