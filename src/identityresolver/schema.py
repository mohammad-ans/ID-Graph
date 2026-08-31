from __future__ import annotations
import re
from pathlib import Path
from typing import Any
import yaml

__all__ = ["SchemaError", "load_schema", "validate_schema", "souce_columns", "signal_columns", "identifier_names", "merge_identifier_names", "feature_names", "field_role", "probabilistic_config", "prolly_enabled", "phone_gap_days", "TIME_SLOTS"]
TIME_SLOTS = (
    ("temporal_same_day", 1),
    ("temporal_same_week", 7),
    ("temporal_same_month", 30),
)
DEFAULT_PHONE_GAP_DAYS = 720
_COLUMN_SAFE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

class SchemaError(ValueError):
    "Column schema is missing keys or is malformed"

def load_schema(path):
    path = Path(path)
    if not path.is_file():
        raise SchemaError(f"Column schema file not found: {path}")
    with open(path, encoding="utf-8") as file:
        schema_cols = yaml.safe_load(file)
    if not isinstance(schema_cols, dict):
        raise SchemaError(f"{path} could not be parsed to a dict")
    validate_schema(schema_cols)
    return schema_cols

def validate_schema(schema_cols):
    if "identifiers" not in schema_cols or not schema_cols["identifiers"]:
        raise SchemaError("Column schema needs at least one entry under 'identifiers'")

    for spec in schema_cols["identifiers"]:
        for key in ("name", "column", "pre_hashed", "edge_tag", "include_in_belongs_to"):
            if key not in spec:
                raise SchemaError(f"Identifier {spec.get('name', spec)!r} is missing '{key}'")
        check_column(spec["column"])

    for group in schema_cols.get("signal_groups", []) or []:
        for key in ("name", "columns", "edge_tag"):
            if key not in group:
                raise SchemaError(f"Signal group {group.get('name', group)!r} is missing '{key}'")
        for column in group["columns"]:
            check_column(column)

    record_id = schema_cols.get("record_id")
    if not record_id:
        raise SchemaError("Column schema needs a 'record_id' entry")
    check_column(record_id[0] if isinstance(record_id, list) else record_id)

    for column in schema_cols.get("passthrough", []) or []:
        check_column(column)

    for role, spec in (schema_cols.get("field_roles") or {}).items():
        if spec.get("source") not in {"attributes", "raw_signals"}:
            raise SchemaError(
                f"field_roles.{role}.source must be 'attributes' or 'raw_signals', "
                f"got {spec.get('source')!r}"
            )
        check_column(spec.get("column", ""))

    if prolly_enabled(schema_cols):
        config = probabilistic_config(schema_cols)
        for key in ("auto_merge_threshold", "review_threshold"):
            if key in config and not 0.0 <= float(config[key]) <= 1.0:
                raise SchemaError(f"probabilistic.{key} must be between 0 and 1")
        for name, mu in (config.get("fields") or {}).items():
            if "m" not in mu or "u" not in mu:
                raise SchemaError(f"probabilistic.fields.{name} needs both 'm' and 'u'")

    return schema_cols

def check_column(name):
    if not isinstance(name, str) or not _COLUMN_SAFE_RE.match(name):
        raise SchemaError(f"{name} is not a safe postgres column name")

def record_id_column(schema_cols):
    record_id = schema_cols["record_id"]
    return record_id[0] if isinstance(record_id, list) else record_id

def signal_columns(schema_cols):
    columns = []
    for group in schema_cols.get("signal_groups", []) or []:
        columns.extend(group["columns"])
    return columns

def identifier_names(schema_cols):
    return [spec["name"] for spec in schema_cols["identifiers"]]

def merge_identifier_names(schema_cols):
    return {spec["name"] for spec in schema_cols["identifiers"] if spec.get("include_in_belongs_to")}

def source_columns(schema_cols):
    columns = list(schema_cols.get("passthrough", []) or [])
    columns.extend(spec["column"] for spec in schema_cols["identifiers"])
    columns.extend(signal_columns(schema_cols))
    columns.append(record_id_column(schema_cols))
    seen = set()
    ordered = []
    for column in columns:
        if column not in seen:
            seen.add(column)
            ordered.append(column)
    return ordered

def field_role(schema_cols, role):
    return (schema_cols.get("field_roles") or {}).get(role)

def field_role_column(schema_cols: dict, role: str) -> str | None:
    spec = field_role(schema_cols, role)
    return spec["column"] if spec else None

def probabilistic_config(schema_cols):
    config = {"auto_merge_threshold": 0.9, "review_threshold": 0.8, "active_learning_min_labels": 15, "fields": {}}
    for item in schema_cols.get("probabilistic", []) or []:
        config.update(item)
    return config
def prolly_enabled(schema_cols):
    for item in schema_cols.get("resolver", []) or []:
        if "probabilistic" in item:
            return bool(item["probabilistic"])
    return False

def features_names(schema_cols):
    names = set(signal_columns(schema_cols))
    if field_role(schema_cols, "temporal"):
        names.update(name for name, _ in TIME_SLOTS)
    behavioral = field_role_column(schema_cols, "behavioral")
    if behavioral:
        names.add(behavioral)
    names.update((probabilistic_config(schema_cols).get("fields") or {}).keys())
    return tuple(sorted(names))

def phone_gap_days(schema_cols):
    rules = schema_cols.get("rules") or {}
    return int(rules.get("phone_gap_days", DEFAULT_PHONE_GAP_DAYS))