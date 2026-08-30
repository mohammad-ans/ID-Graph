from __future__ import annotations

def generate_schema_ngql(schema_cols: dict, space_name: str):
    statements = []
    statements.append(f"CREATE SPACE IF NOT EXISTS {space_name} (partition_num=15, replica_factor=1, vid_type=fixed_string(64))")
    statements.append(f"USE {space_name}")
    passthrough_cols = schema_cols.get("passthrough", [])
    record_props = ", ".join(f"{col} string" for col in passthrough_cols)
    statements.append(f"CREATE TAG IF NOT EXISTS record({record_props})")
    signal_groups = schema_cols.get("signal_groups", [])
    fg_hash_props = ", ".join(f'{group["name"]} string' for group in signal_groups)
    statements.append(f"CREATE TAG IF NOT EXISTS fg_hash({fg_hash_props})")

    statements.append("""
        CREATE TAG IF NOT EXISTS identity_no(
            deprecated bool DEFAULT false,
            merged_into string DEFAULT "",
            resolution_method string DEFAULT "deterministic"
        )
    """)
    identifiers = schema_cols.get("identifiers", [])
    for identifier in identifiers:
        name = identifier["name"]
        statements.append(f"CREATE TAG IF NOT EXISTS {name}(value string)")
        statements.append(f"CREATE EDGE IF NOT EXISTS has_{name}()")
    statements.append("""
        CREATE EDGE IF NOT EXISTS probable_match(
            start_date double,
            end_date string
        )
    """)
    statements.append("""
        CREATE EDGE IF NOT EXISTS probable_match(
            score double,
            method string,
            linked_at string
        )
    """)
    return statements
    