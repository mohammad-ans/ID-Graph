from __future__ import annotations
import math
from dataclasses import dataclass, field as dc_field
from datetime import datetime
import numpy
from graph_model import GraphRow


TIME_SLOTS = (("temporal_same_day", 1), ("temporal_same_week", 7), ("temporal_same_month", 30))

def parse_config(schema_cols: dict) -> dict:
    out = {"auto_merge_threshold": 0.9, "review_threshold": 0.8}
    for item in schema_cols.get("probabilistic", []):
        out.update(item)
    return out

def signal_columns(schema_cols: dict) -> list[str]:
    cols = []
    for group in schema_cols["signal_groups"]:
        cols.extend(group["columns"])
    return cols

def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.isoformat(value)
    except (TypeError, ValueError):
        return None

def pair_features(row_a: GraphRow, row_b: GraphRow, schema_cols: dict) -> dict[str, bool]:
    features= {}
    for col in signal_columns(schema_cols):
        a, b = row_a.raw_signals.get(col), row_b.raw_signals.get(col)
        features[col] = a is not None and a == b
    date_a = parse_date(row_a.attributes.get("transaction_date"))
    date_b = parse_date(row_b.attributes.get("transaction_date"))
    gap_days = None
    if date_a and date_b:
        gap_days = abs((date_a - date_b).days)
    if gap_days is not None:
        for name, window in TIME_SLOTS:
            if gap_days <= window:
                features[name] = gap_days
    merchant_a = row_a.attributes.get("merchant_name")
    merchant_b = row_b.attributes.get("merchant_name")
    features["merchant_name"] = merchant_a is not None and merchant_a == merchant_b
    return features
