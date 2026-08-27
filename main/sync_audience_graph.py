from __future__ import annotations
import yaml
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Iterable
from collections import defaultdict
import psycopg2
import psycopg2.extras
from psycopg2.extensions import connection as _T_conn
from config import NebulaConfig, PostgresConfig, SyncConfig
from graph_model import GraphRow, row_to_ngql, belongs_to_identity, add_probable_identity, get_identities, vid
from nebula_client import NebulaClient
from batch_id_union import cluster_identifiers, distinct_identifiers
from probability import resolve_prolly, prolly_enabled, PoolRow, blocking_key, FellegiSunterModel, should_refit, score_guest, statements_reconciliation
from active_learning import maybe_fit
import re
import json


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


_COLUMN_SAFE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
def validate_column_name(name: str):
    if not _COLUMN_SAFE_RE.match(name):
        raise ValueError(f"Unsafe or invalid column name in config: {name!r}")

ROWS_PER_NEBULA_SESSION = 100


@dataclass(frozen=True)
class SyncResult:
    table_name: str
    rows_synced: int
    dry_run: bool


def connect_postgres(config: PostgresConfig):
    logger.info("Opening Postgres connection to %s:%s/%s", config.host, config.port, config.dbname)
    return psycopg2.connect(
        host=config.host,
        port=config.port,
        dbname=config.dbname,
        user=config.user,
        password=config.password,
        connect_timeout=10,
        keepalives=1,
        keepalives_idle=60,
        keepalives_interval=10,
        keepalives_count=5,
    )

def ensure_probable_match_table(conn: _T_conn, schema_name: str, table_name: str = "probable_match"):
    logger.info(f"Ensuring {schema_name}.{table_name} exists")
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema_name}.{table_name} (
                record_id text PRIMARY KEY,
                identity_no text NOT NULL,
                row_data JSONB NOT NULL.
                blocking_key_country text,
                blocking_key_week text,
                linked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute(f"""
            CREATE INDEX IF NOT EXISTS {table_name}_blocking_idx ON {schema_name}.{table_name} (blocking_key_country, blocking_key_week)
        """)
        cur.execute(f"""
            CREATE INDEX IF NOT EXISTS {table_name}_identity_idx ON {schema_name}.{table_name} (identity_no)
        """)
        conn.commit()
        logger.info("Probable match table done")

def insert_into_probable_match(conn: _T_conn, rows: list, identity_no: str, schema_name: str, table_name: str = "probable_match"):
    if not rows:
        return
    with conn.cursor() as cur:
        args = []
        for row in rows:
            pool_row = row if isinstance(row, PoolRow) else PoolRow.from_graph_row(row)
            country, week = blocking_key(pool_row)
            args.append((pool_row.record_id, identity_no, country, week, json.dumps(pool_row.to_dict())))
            cur.executemany(f"""
                INSERT INTO {schema_name}.{table_name}
                (record_id, identity_no, blocking_key_country, blocking_key_week, row_data)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (record_id) DO UPDATE SET
                identity_no = EXCLUDED.identity_no, row_data=EXCLUDED.row_data
            """, args)
    conn.commit()

def fetch_probable_match_candidates(conn: _T_conn, blocking_keys: set[tuple], schema_name: str, table_name: str = "probable_match_index"):
    if not blocking_keys:
        return []
    rows = []
    with conn.cursor() as cur:
        countries = list({key[0] for key in blocking_keys})
        weeks = list({key[1] for key in blocking_keys})
        cur.execute(f"""
            SELECT row_data FROM {schema_name}.{table_name}
            WHERE blocking_key_country = ANY(%s) AND blocking_key_week = ANY(%s)
        """, (countries, weeks))
        rows = cur.fetchall()
    exact = []
    for (row, ) in rows:
        pool_row = PoolRow.from_dict(row)
        if blocking_key(pool_row) in blocking_keys:
            exact.append(pool_row)
    return exact 

def remove_identity_probable_match(conn: _T_conn, identity: str, schema_name: str, table_name: str = "probable_match_index"):
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {schema_name}.{table_name} WHERRE identity_no = %s", (identity,))
    conn.commit()

def ensure_main_table(conn: _T_conn, schema_name: str, table_name: str = "record_identities"):
    logger.info(f"Ensuring {schema_name}.{table_name} exists")
    with conn.cursor() as cur:
        cur.execute(
            f"""CREATE TABLE IF NOT EXISTS {schema_name}.{table_name} (
                record_id text PRIMARY KEY,
                identity_no text NOT NULL,
                resolution_method text NOT NULL DEFAULT 'deterministic',
                updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
            );"""
        )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schemas = %s AND table_name = %s)", (schema_name, table_name)
        )
        exists = cur.fetchone()
        if not exists:
            raise RuntimeError("main table of identities not found, check postgres")
    logger.info(f"{schema_name}.{table_name} done")

def insert_identities(conn: _T_conn, resolved: dict[str, tuple[str, str]], schema_name: str, table_name: str = "record_identities"):
    if not resolved:
        return
    args = [(record_id, identity, method) for record_id, (identity, method) in resolved.items()]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur,
            f"""
                INSERT INTO {schema_name}.{table_name} (record_id, identity_no, resolution_method) 
                VALUES %s 
                ON CONFLICT (record_id) DO UPDATE SET 
                identity_no = EXCLUDED.identity_no,
                resolution_method = EXCLUDED.resolution_method
            """, args, page_size=1000
        )
    conn.commit()
    logger.info(f"Completed updating the main identities table with {len(resolved)} updations")

def ensure_log_tables(conn: _T_conn, schema_name: str):
    logger.info(f"Ensuring {schema_name}.merge_logs and {schema_name}.remap_logs exist")
    
    with conn.cursor() as cur:
        cur.execute(
            f"""CREATE TABLE IF NOT EXISTS {schema_name}.merge_logs (
            merge_id BIGSERIAL PRIMARY KEY, 
            source_rampid text NOT NULL, 
            target_rampid text NOT NULL, 
            identifiers TEXT[], 
            done_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)
        cur.execute(
            f"""CREATE TABLE IF NOT EXISTS {schema_name}.remap_logs (
            remap_id BIGSERIAL PRIMARY KEY, 
            source_rampid text NOT NULL,
            target_rampid text NOT NULL,
            remap_type INTEGER NOT NULL,
            done_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP);"""
        )
    conn.commit()
    logger.info("Merge and remap log tables done")

def ensure_invalids_table(conn : _T_conn, schema_name : str, identifiers_table : str = "graph_invalid_identifiers"):
    logger.info(f"Ensuring {schema_name}.{identifiers_table}")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema_name}.{identifiers_table} (
                identifier_type text NOT NULL,
                identifier text NOT NULL,
                PRIMARY KEY (identifier, identifier_type)
            );
            """
        )
    conn.commit()
    logger.info("Invalid Table Ready")

def ensure_audit_table(conn : _T_conn, schema_name : str, sync_table : str):
    logger.info(f"Ensuring {schema_name}.{sync_table} exists")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema_name}.{sync_table} (
              graph_name text NOT NULL,
              standardized_table text NOT NULL,
              source_table text NOT NULL,
              record_id text NOT NULL,
              synced_at timestamp NOT NULL DEFAULT now(),
              PRIMARY KEY (graph_name, standardized_table, source_table, record_id)
            );
            """
        )
    conn.commit()
    logger.info("Audit table ready")

def ensure_review_queue(conn: _T_conn, schema_name: str, review_table: str = "identity_review_queue"):
    logger.info(f"Ensuring {schema_name}.{review_table} exists")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema_name}.{review_table} (
                review_id BIGSERIAL PRIMARY KEY,
                record_id_a text NOT NULL,
                record_id_b text NOT NULL,
                score DOUBLE PRECISION NOT NULL,
                features JSONB NOT NULL,
                status text NOT NULL DEFAULT 'pending',
                created_at timestamp NOT NULL DEFAULT now(),
                decision text,
                decided_at timestamp,
                CHECK (status IN ('pending', 'confirmed', 'rejected'))
            );
            """
        )
    conn.commit()
    logger.info("Review queue table ready")

def insert_review_candidates(conn: _T_conn, candidates: list[tuple], schema_name: str, review_table : str = "identity_review_queue"):
    if not candidates:
        return
    with conn.cursor() as cur:
        args = [(a, b, score, json.dumps(features)) for a, b, score, features in candidates]
        cur.executemany(
            f"INSERT INTO {schema_name}.{review_table} (record_id_a, record_id_b, score, features) VALUES (%s, %s, %s, %s)", args
        )
    conn.commit()

def ensure_candidate_pool(conn: _T_conn, schema_name: str, pool_table: str = "unresolved_candidate_pool"):
    logger.info(f"Ensuring {schema_name}.{pool_table} exists")
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema_name}.{pool_table} (
                record_id text PRIMARY_KEY,
                blocking_key_country text,
                blocking_key_week text,
                row_data JSONB NOT NULL,
                first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );"""
        )
        cur.execute(f"""
            CREATE INDEX IF NOT EXISTS {pool_table}_blocking_idx
            ON {schema_name}.{pool_table} (blocking_key_country, blocking_key_week)
        """)
    conn.commit()
    logger.info("Candidate pool table done")

def insert_into_pool(conn: _T_conn, rows: list, schema_name: str, pool_table: str = "unresolved_candidate_pool"):
    if not rows:
        return
    with conn.cursor() as cur:
        args = []
        for row in rows:
            pool_row = row if isinstance(row, PoolRow) else PoolRow.from_graph_row(row)
            country, week = blocking_key(pool_row)
            args.append((pool_row.record_id, country, week, json.dumps(pool_row.to_dict())))
        cur.executemany(f"""
            INSERT INTO {schema_name}.{pool_row}
            (record_id, blocking_key_country. blocking_key_week, row_data, last_seen_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (record_id) DO UPDATE SET
            row_data = EXCLUDED.row_data, last_seen_at = CURRENT_TIMESTAMP
        """, args
        )
    conn.commit()

def remove_from_pool(conn: _T_conn, records_ids: set[str], schema_name: str, pool_table: str = "unresolved_candidate_pool"):
    if not records_ids:
        return
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM {schema_name}.{pool_table} WHERE record_id = ANY(%s)", (list(records_ids), ))
    conn.commit()

def fetch_invalid(conn : _T_conn, tablename : str, max_transactions : int, remap_type : int, schema_name : str, schema_cols: dict, invalid_table : str = "graph_invalid_identifiers"):
    logger.info("Getting supernode identifiers from database")
    invalid_identifiers = defaultdict(set)
    cur = conn.cursor()
    for identifier in schema_cols["identifiers"]:
        col = identifier["column"]
        validate_column_name(col)
        cur.execute(
            f"""
            SELECT {col}
            FROM {schema_name}.{tablename}
            WHERE {col} IS NOT NULL
            GROUP BY {col}
            HAVING COUNT(*) > {max_transactions};
            """
        )
        identifiers = set(row[0] for row in cur.fetchall())
        invalid_identifiers[col].update(identifiers)
    if remap_type == 3:
        cur.execute(
            f"""
            SELECT identifier_type, identifier
            FROM {schema_name}.{invalid_table};
            """
        )
        for row in cur.fetchall():
            invalid_identifiers[row[0]].add(row[1])
    cur.close()
    return invalid_identifiers

def fetch_pool_candidates(conn:_T_conn, blocking_keys: set[tuple], schema_name: str, pool_table: str = "unresolved_candidate_pool"):
    if not blocking_keys:
        return []
    with conn.cursor() as cur:
        countries = set()
        weeks = set()
        for country, week in blocking_keys:
            countries.add(country)
            weeks.add(week)
        countries = list(countries)
        weeks = list(weeks)
        cur.execute(f"""
            SELECT row_data FROM {schema_name}.{pool_table}
            WHERE blocking_key_country = ANY(%s) AND blocking_key_week = ANY(%s)
            """, (countries, weeks))
        rows = cur.fetchall()
    exact = []
    for (row_data,) in rows:
        pool_row = PoolRow.from_dict(row_data)
        if blocking_key(pool_row) in blocking_keys:
            exact.append(pool_row)
    return exact

def ensure_candidate_history(conn: _T_conn, schema_name: str, history_table: str = "fellegi_sunter_candidate_history"):
    logger.info(f"Ensuring {schema_name}.{history_table} exists")
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema_name}.{history_table} (
                history_id BIGSERIAL PRIMARY KEY,
                record_id_a text NOT NULL,
                record_id_b text NOT NULL,
                features JSONB NOT NULL,
                score DOUBLE PRECISION NOT NULL,
                outcome text NOT NULL,
                scored_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (outcome IN ('auto_merge'm 'review', 'reject'))
            );
        """)
    conn.commit()
    logger.info("Candidate history table done")

def insert_candidate_history(conn: _T_conn, scored: list[tuple], schema_name: str, history_table: str = "fellegi_sunter_candidate_history"):
    if not scored:
        return
    with conn.cursor() as cur:
        args = [(a, b, score, json.dumps(features), outcome) for a, b, score, features, outcome in scored]
        cur.executemany(f"""
            INSERT INTO {schema_name}.{history_table}
            (record_id_a, record_id_b, score, features, outcome)
            VALUES (%s, %s, %s, %s, %s)
        """, args
        )
    conn.commit()

def fetch_candidate_features(conn: _T_conn, schema_name: str, history_table: str = "fellegi_sunter_candidate_history", limit: int = 5000):
    with conn.cursor() as cur:
        cur.execute(f"SELECT features FROM {schema_name}.{history_table} ORDER_BY scored_at DESC LIMIT %S", (limit, ))
    return [row[0] for row in cur.fetchall()]

def count_candidates_history(conn: _T_conn, schema_name: str, history_table: str = "fellegi_sunter_candidate_history"):
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {schema_name}.{history_table}")
        return cur.fetchone()[0]

def ensure_model_params(conn: _T_conn, schema_name: str, params_table: str = "fellegi_sunter_model_params"):
    logger.info(f"Ensuring {schema_name}.{params_table} exists")
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {schema_name}.{params_table} (
                param_id BIGSERIAL PRIMARY KEY,
                m_probs JSONB NOT NULL,
                u_probs JSONB NOT NULL,
                prior_match_probability DOUBLE PRECISION NOT NULL,
                history_rows_used INTEGER NOT NULL,
                fitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
    conn.commit()
    logger.info("Model params done")

def load_latest_model(conn: _T_conn, schema_name: str, params_table: str = "fellegi_sunter_model_params"):
    with conn.cursor() as cur:
        cur.execute(f"SELECT m_probs, u_probs, prior_match_probability FROM {schema_name}.{params_table} ORDER BY fitted_at DESC LIMIT 1")
        row = cur.fetchone()
    if row is None:
        return None
    m_probs, u_probs, prior = row
    return FellegiSunterModel.from_dict({"m_probs": m_probs, "u_probs" : u_probs, "prior_match_probability": prior})

def save_model(conn: _T_conn, model, history_rows_used: int, schema_name: str, params_table: str = "fellegi_sunter_model_params"):
    d = model.to_dict()
    with conn.cursor() as cur:
        cur.execute(f"""
            INSERT INTO {schema_name}.{params_table}
            (m_probs, u_probs, prior_match_probability, history_rows_used)
            VALUES (%s, %s, %s, %s)
        """, (json.dumps(d["m_probs"]), json.dumps(d["u_probs"]), d["prior_match_probability"], history_rows_used) )
    conn.commit()

def insert_invalid_identifiers(conn : _T_conn, identifiers: list[tuple], schema_name : str, invalid_table : str = "graph_invalid_identifiers"):
    with conn.cursor() as cur:
        cur.execute(
            f"""
                INSERT INTO {schema_name}.{invalid_table} (identifier_type, identifier)
                VALUES {", ".join(f"(%s, %s)" for _ in identifiers)}
                ON CONFLICT DO NOTHING;
            """, (", ".join(f"('{identifier[0]}', '{identifier[1]}')" for identifier in identifiers))
        )
    conn.commit()
    logger.info("Invalid identifiers added")


def mark_synced(conn : _T_conn, graph_name: str, rows: Iterable[GraphRow], schema_name : str, sync_table : str):
    values = [
        (graph_name, row.attributes.get("standardized_table", "unknown") or "unknown", row.attributes.get("source_table", "unknown") or "unknown", row.record_id)
        for row in rows
    ]
    if not values:
        return

    logger.info("Marking %s graph rows as synced in audit table", len(values))

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            f"""
            INSERT INTO {schema_name}.{sync_table} (
              graph_name,
              standardized_table,
              source_table,
              record_id
            )
            VALUES %s
            ON CONFLICT (graph_name, standardized_table, source_table, record_id)
            DO UPDATE SET synced_at = now();
            """,
            values,
            page_size=1000,
        )
    conn.commit()


def fetch_rows(conn : _T_conn, graph_name: str, table_name: str, columns: list[str], batch_size: int, schema_name : str, sync_table : str, schema_cols: dict):
    for column in columns:
        validate_column_name(column)
    column_sql = ", ".join(f't."{column}"' for column in columns)
    logger.info("Opening streamed source read: table=%s graph=%s batch_size=%s", table_name, graph_name, batch_size)
    query = f"""
        SELECT
          'sync_{table_name}' AS standardized_table,
          {column_sql}
        FROM {schema_name}."{table_name}" t
        LEFT JOIN {schema_name}.{sync_table} a
          ON a.graph_name = %s
         AND a.standardized_table = %s
         AND a.source_table = COALESCE(t.source_table, 'unknown')
         AND a.record_id = t.record_id
        WHERE t.record_id IS NOT NULL
          AND a.record_id IS NULL
        ORDER BY t.record_id;
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.itersize = batch_size
        cur.execute(query, (table_name, graph_name, table_name))
        batch = []
        batch_no = 0
        for row in cur:
            batch.append(GraphRow.from_db_row(dict(row), schema_cols))
            if len(batch) >= batch_size:
                batch_no += 1
                logger.info("Fetched graph batch %s from %s: rows=%s", batch_no, table_name, len(batch))
                yield batch
                batch = []
        if batch:
            batch_no += 1
            logger.info("Fetched final graph batch %s from %s: rows=%s", batch_no, table_name, len(batch))
            yield batch
    logger.info("Finished streamed source read for %s", table_name)


def write_batch(nebula: NebulaClient, rows: list[GraphRow], max_workers: int):

    row_chunks = [
        rows[idx:idx + ROWS_PER_NEBULA_SESSION]
        for idx in range(0, len(rows), ROWS_PER_NEBULA_SESSION)
    ]
    logger.info(
        "Writing graph batch to Nebula: rows=%s session_chunks=%s max_workers=%s",
        len(rows),
        len(row_chunks),
        max_workers,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                nebula.execute_many,
                [statement for row in chunk for statement in row_to_ngql(row)],
                100,
            ): idx
            for idx, chunk in enumerate(row_chunks)
        }
        for future in as_completed(futures):
            future.result()

def write_identity_queries(nebula: NebulaClient, statements: list[str]):
    logger.info(
        "Doing identity resolution queries"
    )
    nebula.execute_many(statements, 100)


def fetch_identities(chunk : list[str], nebula : NebulaClient, max_workers: int):

    chunks = [
        chunk[idx: idx + ROWS_PER_NEBULA_SESSION]
        for idx in range(0, len(chunk), ROWS_PER_NEBULA_SESSION)
    ]

    logger.info(
        "Getting identifiers and identities batch from Nebula: total_query_size=%s",
        len(chunk)
    )
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                    fetch_identities_batch,
                    chunk,
                    nebula,
                        ): idx
                    for idx, chunk in enumerate(chunks)
        }
        combined = {}
        for future in as_completed(futures):
            try:
                combined.update(future.result())
            except Exception as exc:
                raise RuntimeError(f"Chunk fetch failed {exc}" ) from exc
        return combined



def fetch_identities_batch(chunk : list[str], nebula : NebulaClient):
    vid_list = ", ".join(f'"{vid}"' for vid in chunk)
    query = (
        f'GO FROM {vid_list}'
        f' OVER belongs_to WHERE properties(edge).end_date == "" '
        f'YIELD src(edge) AS identifier_vid, dst(edge) AS identity_vid'
    )
    result = nebula.execute(query)
    mapping = {}
    for row in result.rows():
        identifier_vid = row.values[0].get_sVal().decode("utf-8")
        identity_vid = row.values[1].get_sVal().decode("utf-8")
        mapping[identifier_vid] = identity_vid
    return mapping

def row_vids_(row: GraphRow):
    return [vid(id_type, val) for id_type, val in row.identifiers.items() if val]

def reconcile_new_identities(conn, batch: list[GraphRow], unresolvable: list[GraphRow], identifier_identity_map: dict, schema_cols: dict, model, schema_name: str, table_name: str, nebula: NebulaClient):
    if not prolly_enabled(schema_cols):
        return 0
    unresolvable_ids = {row.record_id for row in unresolvable}
    identified = []
    for row in batch:
        if row.record_id in unresolvable_ids:
            continue
        row_vids = row_vids_(row)
        if row_vids and any(v in identifier_identity_map for v in row_vids):
            identified.append(row)

    if not identified:
        return 0
    blocking_keys = {blocking_key(row) for row in identified}
    candidates = fetch_probable_match_candidates(conn, blocking_keys, schema_name)
    if not candidates:
        return 0
    
    count = 0
    for row in identified:
        if not candidates:
            break
        results = score_guest(row, candidates, schema_cols, model)
        if not results:
            continue

        current_map = fetch_identities(row_vids_(row), nebula, 1)
        new_identity_vids = set(current_map.values())
        if not new_identity_vids:
            logger.info("Candidate %s scored a match but no current identity yet so skipping it", row.record_id)
            continue
        best = results[0]
        for identity_vid in new_identity_vids:
            nebula.execute_many(statements_reconciliation(best.probable_identity, identity_vid))
        remove_identity_probable_match(conn, best.probable_identity, schema_name)
        candidates = [c for c in candidates if c.identity_no != best.probable_identity]
        count += 1
        logger.info("Merged probable match identity %s into %s for %s (record %s, score=%.4f)", best.probable_identity, sorted(new_identity_vids), table_name, row.record_id, best.score)

    return count

def sync_table(
    read_conn,
    audit_conn,
    nebula: NebulaClient | None,
    graph_name: str,
    table_name: str,
    sync_config: SyncConfig,
    schema_cols: dict | None = None,
    cols_list: list[str] = [],
    prob_model: FellegiSunterModel | None = None
) -> SyncResult:
    total = 0
    logger.info(
        "Starting graph sync for %s batch_size=%s max_records=%s dry_run=%s write_concurrency=%s phone_gap=%s",
        table_name,
        sync_config.batch_size,
        sync_config.max_records,
        sync_config.dry_run,
        sync_config.write_concurrency,
        sync_config.phone_gap
    )
    static_invalid_identifiers = fetch_invalid(read_conn, table_name, sync_config.max_transactions, sync_config.remap_type, sync_config.schema_name, schema_cols)
    for batch in fetch_rows(read_conn, graph_name, table_name, cols_list, sync_config.batch_size, sync_config.schema_name, sync_config.sync_table, schema_cols):
        if sync_config.max_records is not None and total >= sync_config.max_records:
            break

        if sync_config.max_records is not None:
            remaining = sync_config.max_records - total
            batch = batch[:remaining]
            logger.info("Applying max_records cap for %s: remaining=%s batch_rows=%s", table_name, remaining, len(batch))

        if sync_config.dry_run:

            clustered_identifiers, transaction_dates, unresolvable = cluster_identifiers(batch, static_invalid_identifiers, sync_config.phone_gap, schema_cols)
            all_identifiers = distinct_identifiers(clustered_identifiers)

            identifier_identity_map = {}
            if not sync_config.phone_gap:
                transaction_dates = None
            statements, invalid_identifiers_declare, db_statements = belongs_to_identity(identifier_identity_map, clustered_identifiers, transaction_dates, sync_config.max_identifiers, sync_config.remap_type, schema_cols, nebula)
            
            preview_statements = row_to_ngql(batch[0]) if batch else []
            logger.info(
                "Dry run for %s: would sync %s rows; example statements:\n%s. Invalid identifiers: %s and data base audit tables statements %s",
                table_name, len(batch), ";\n".join(preview_statements), ",".join(invalid_identifiers_declare), ";\n".join(db_statements)
            )

            total += len(batch)
            if sync_config.max_records is not None and total >= sync_config.max_records:
                logger.info("Reached max_records for %s: %s", table_name, sync_config.max_records)
                break
            continue
        
        clustered_identifiers, transaction_dates, unresolvable = cluster_identifiers(batch, static_invalid_identifiers, sync_config.phone_gap, schema_cols)
        all_identifiers = distinct_identifiers(clustered_identifiers)
        identifier_identity_map = fetch_identities(all_identifiers, nebula, 2)
        if not sync_config.phone_gap:
            transaction_dates = None
        statements, invalid_identifiers_declare, db_statements = belongs_to_identity(identifier_identity_map, clustered_identifiers, transaction_dates, sync_config.max_identifiers, sync_config.remap_type, schema_cols, nebula)
        if sync_config.remap_type == 3 and invalid_identifiers_declare:
            insert_invalid_identifiers(audit_conn, invalid_identifiers_declare, sync_config.schema_name)
        if unresolvable and prolly_enabled(schema_cols):
            classifier = maybe_fit(audit_conn, schema_cols, sync_config.schema_name)
            blocking_keys = {blocking_key(row) for row in unresolvable}
            pool_candidates = fetch_pool_candidates(audit_conn, blocking_keys, sync_config.schema_name)
            prob_result = resolve_prolly(unresolvable, schema_cols, prob_model, classifier, pool_rows=pool_candidates)
            for group_rows, score in prob_result.auto_merge_groups:
                group_statements, identity = add_probable_identity(group_rows, score)
                statements.extend(group_statements)
                insert_into_probable_match(audit_conn, group_rows, identity, sync_config.schema_name)
            if prob_result.review_candidates:
                review_rows = [(row_a.record_id, row_b.record_id, score, features) for row_a, row_b, score, features in prob_result.review_candidates]
                insert_review_candidates(audit_conn, review_rows, sync_config.schema_name)
            remove_from_pool(audit_conn, prob_result.matched_pool_records, sync_config.schema_name)
            insert_into_pool(audit_conn, prob_result.unmatched_new, sync_config.schema_name)
            insert_candidate_history(audit_conn, prob_result.all_scored, sync_config.schema_name)

            logger.info(
                f"Probabilistic linkage for {table_name}: {len(unresolvable)} converted to {len(prob_result.auto_merge_groups)} auto merges and {len(prob_result.review_candidates)} review candidates and {prob_result.rejected_count} rejected"
            )
        
        write_batch(nebula, batch, max_workers=sync_config.write_concurrency)
        write_identity_queries(nebula, statements)
        count = reconcile_new_identities(audit_conn, batch, unresolvable, identifier_identity_map, schema_cols, prob_model, sync_config.schema_name, table_name, nebula)
        if count:
            logger.info("Reconciled %s probable_match identit%s with a deterministic identifier in %s", count, "y" if count == 1 else "ies", table_name)
        resolved = get_identities(batch, nebula)
        insert_identities(audit_conn, resolved, sync_config.schema_name)
        mark_synced(audit_conn, graph_name, batch, sync_config.schema_name, sync_config.sync_table)
        total += len(batch)
        logger.info("Synced %s rows from %s (running total)", total, table_name)
        if sync_config.max_records is not None and total >= sync_config.max_records:
            logger.info("Reached max_records for %s: %s", table_name, sync_config.max_records)
            break

    logger.info("Completed graph sync for %s: rows_synced=%s", table_name, total)
    return SyncResult(table_name=table_name, rows_synced=total, dry_run=sync_config.dry_run)


def run_sync(
    max_identifiers: int | None = None,
    max_transactions: int | None = None,
    tables: str | None = None,
    batch_size: int | None = None,
    max_records: int | None = None,
    write_concurrency: int | None = None,
    dry_run: bool = False,
    phone_gap: bool = False,
    remap_type: int = 0,
    schema_name: str | None = None,
    sync_table_name: str | None = None,
    schema_cols: dict | None = None,
    cols_list: list[str] = []

) -> dict:
    
    pg_config = PostgresConfig.from_env()
    nebula_config = NebulaConfig.from_env()
    env_sync_config = SyncConfig.from_env()
    sync_config = SyncConfig(
        max_transactions=max_transactions or env_sync_config.max_transactions,
        max_identifiers=max_identifiers or env_sync_config.max_identifiers,
        batch_size=batch_size or env_sync_config.batch_size,
        max_records=max_records if max_records is not None else env_sync_config.max_records,
        dry_run=dry_run or env_sync_config.dry_run,
        phone_gap=phone_gap or env_sync_config.phone_gap,
        remap_type=remap_type or env_sync_config.remap_type,
        schema_name=schema_name,
        sync_table=sync_table_name,
        write_concurrency=write_concurrency or env_sync_config.write_concurrency,
    )
    table_list = [
        t.strip()
        for t in (tables).split(",")
        if t.strip()
    ]
    
    results: dict[str, int] = {}
    logger.info(
        "Graph sync configured: max_transactions=%s max_identifiers=%s tables=%s columns=%s batch_size=%s max_records=%s dry_run=%s write_concurrency=%s",
        sync_config.max_transactions,
        sync_config.max_identifiers,
        table_list,
        schema_cols,
        sync_config.batch_size,
        sync_config.max_records,
        sync_config.dry_run,
        sync_config.write_concurrency,
    )
    nebula = NebulaClient(nebula_config)
    with connect_postgres(pg_config) as read_conn, connect_postgres(pg_config) as audit_conn:
        ensure_audit_table(audit_conn, sync_config.schema_name, sync_config.sync_table)
        ensure_log_tables(audit_conn, sync_config.schema_name)
        ensure_main_table(audit_conn, sync_config.schema_name)
        if sync_config.remap_type == 3:
            ensure_invalids_table(audit_conn, sync_config.schema_name)
        if schema_cols and prolly_enabled(schema_cols):
            ensure_review_queue(audit_conn, sync_config.schema_name)
            ensure_candidate_pool(audit_conn, sync_config.schema_name)
            ensure_candidate_history(audit_conn, sync_config.schema_name)
            ensure_model_params(audit_conn, sync_config.schema_name)
            ensure_probable_match_table(audit_conn, schema_name)
        prob_model = None
        if schema_cols and prolly_enabled(schema_cols):
            prob_model = load_latest_model(audit_conn, sync_config.schema_name)
            count = count_candidates_history(audit_conn, sync_config.schema_name)
            if should_refit(count):
                feature_rows = fetch_candidate_features(audit_conn, sync_config.schema_name)
                prob_model.fit_em(feature_rows)
                save_model(audit_conn, prob_model, count, sync_config.schema_name)
            
        if sync_config.dry_run:
            for table in table_list:
                result = sync_table(read_conn, audit_conn, None, nebula_config.space, table, sync_config, schema_cols, cols_list, prob_model)
                results[table] = result.rows_synced
            return results

        with NebulaClient(nebula_config) as nebula:
            for table in table_list:
                result = sync_table(read_conn, audit_conn, nebula, nebula_config.space, table, sync_config, schema_cols, cols_list, prob_model)
                logger.info("Finished %s: %s rows synced", result.table_name, result.rows_synced)
                results[table] = result.rows_synced

    return results


def parse_args():
    parser = argparse.ArgumentParser(description="Sync standardized audience rows into Nebula Graph.")
    parser.add_argument(
        "--tables",
        default=None,
        help="Comma-separated standardized table names to sync.",
    )
    parser.add_argument(
        "--columns",
        default=None,
        help="Comma-separated standardized table columns to sync"
    )
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--max-records", type=int, default=None)
    parser.add_argument("--write-concurrency", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-identifiers", type=int, default=None)
    parser.add_argument("--max-transactions", type=int, default=None)
    parser.add_argument("--phone-gap", action="store_true")
    parser.add_argument("--remap-type", type=int, default=0)
    parser.add_argument("--schema-name", default=None)
    parser.add_argument("--sync-table", default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    cols_list = None
    with open("schema.yaml") as file:
        schema_cols = yaml.safe_load(file)
        cols_list = list(schema_cols["passthrough"])
        cols_list.extend(element["column"] for element in schema_cols["identifiers"])
        for element in schema_cols["signal_groups"]:
            cols_list.extend(element["columns"])
        cols_list.append(schema_cols["record_id"][0])

    run_sync(
        max_identifiers = args.max_identifiers,
        max_transactions=args.max_transactions,
        tables=args.tables,
        batch_size=args.batch_size,
        max_records=args.max_records,
        write_concurrency=args.write_concurrency,
        dry_run=args.dry_run,
        phone_gap=args.phone_gap,
        remap_type=args.remap_type,
        schema_name=args.schema_name,
        sync_table_name=args.sync_table,
        schema_cols=schema_cols,
        cols_list = cols_list
    )


if __name__ == "__main__":
    main()