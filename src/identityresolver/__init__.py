from __future__ import annotations
from typing import TYPE_CHECKING, Any
__version__="0.1.0"
from .config import ConfigError, NebulaConfig, PostgresConfig, SyncConfig, load_dotenv_file
from .schema import SchemaError, features_names, load_schema, prolly_enabled, source_columns, validate_schema

if TYPE_CHECKING:
    from .apply_schema import apply_schema
    from .initialize_nebula import initialize_nebula
    from .loadcsv import load_csv, load_csv_file
    from .postgres import connect_postgres
    from .review import review_candidates
    from .sync_audience_graph import run_sync

LAZY: dict[str, str] = {
    "run_sync": ".sync_audience_graph",
    "load_csv_file": ".loadcsv",
    "load_csv": ".loadcsv",
    "apply_schema": ".apply_schema",
    "initialize_nebula": ".initialize_nebula",
    "review_candidates": ".review",
    "connect_postgres": ".postgres",
    "NebulaClient": ".nebula_client",
    "GraphRow": ".graph_model",
    "FellegiSunterModel": ".probability",
}

def __getattr__(name: str):
    module_name = LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attributes {name!r}")
    from importlib import import_module
    val = getattr(import_module(module_name, __name__), name)
    globals()[name] = val
    return val

def __dir__() -> list[str]:
    return sorted(__all__)

__all__ = [
    "__version__",
    "PostgresConfig",
    "NebulaConfig",
    "SyncConfig",
    "ConfigError",
    "load_dotenv_file",
    # column schema
    "load_schema",
    "validate_schema",
    "source_columns",
    "feature_names",
    "probabilistic_enabled",
    "SchemaError",
    # pipeline
    "run_sync",
    "load_csv",
    "load_csv_file",
    "apply_schema",
    "initialize_nebula",
    "review_candidates",
    "connect_postgres",
    "NebulaClient",
    "GraphRow",
    "FellegiSunterModel",
]
app = typer.Typer()
