from __future__ import annotations
import typer, json, logging, sys
from pathlib import Path
from typing import Optional

from . import __version__
from .config import ConfigError, NebulaConfig, PostgresConfig, load_dotenv_file
from .schema import SchemaError, load_schema

app = typer.Typer(name="identityresolver", help="Deterministic and probabilistc identity resolution over Nebula Graph", no_args_is_help=True, add_completion=False)

def setup_logging(verbose):
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

def load_env(env_file: Optional[Path]):
    if env_file is not None:
        load_dotenv_file(env_file, override=False)

def postgres_config(env_file: Optional[Path], db_url: Optional[str], host: Optional[str], port: Optional[str], dbname: Optional[str], user: Optional[str], password: Optional[str]):
    load_env(env_file)
    if db_url:
        base = PostgresConfig.from_url(db_url)
    else:
        try:
            base = PostgresConfig.from_env()
        except ConfigError:
            if not dbname:
                raise typer.BadParameter("No postgres connection given. Pass --db-name, or --db-url, or set DB_NAME in the environment or --env-file") from None
            base = PostgresConfig(dbname=dbname)
        return base.merged(host=host, port=port, dbname=dbname, user=user, password=password)

def nebula_config(env_file: Optional[Path], host: Optional[str], port: Optional[int], username: Optional[str], password: Optional[str], space: Optional[str]) -> NebulaConfig:
    load_env(env_file)
    try:
        base = NebulaConfig.from_env()
    except ConfigError:
        if not space:
            raise typer.BadParameter("No Nebula space given. Pass --space or set NEBULA_SPACE in the environment or --env-file") from None
        base = NebulaConfig(space=space)
    return base.merged(host=host, port=port, username=username, password=password, space=space)

def load_schema_exit(path: Path):
    try:
        return load_schema(path)
    except SchemaError as e:
        typer.secho(f"Column schema error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from e

EnvFile = typer.Option(None, "--env-file", help="Read connection settings from a dotenv file.")
Verbose = typer.Option(False, "--verbose", "-v", help="Debug-level logging.")
DbUrl = typer.Option(None, "--db-url", help="Postgres DSN, e.g. postgresql://user:pw@host:5432/db")
DbHost = typer.Option(None, "--db-host")
DbPort = typer.Option(None, "--db-port")
DbName = typer.Option(None,  "--db-name")
DbUser = typer.Option(None, "--db-user")
DbPass = typer.Option(None, "--db-password")

NebulaHost = typer.Option(None, "--nebula-host")
NebulaPort = typer.Option(None, "--nebula-port")
NebulaUser = typer.Option(None, "--nebula-user")
NebulaPass = typer.Option(None, "--nebula-password")
NebulaSpace = typer.Option(None, "--space", help="Nebula graph space to write into.")

@app.callback(invoke_without_command=True)
def root(ctx: typer.Context, version: bool = typer.Option(False, "--version", help="Print the version and exit.", is_eager=True)) -> None:
         if version:
             typer.echo(__version__)
             raise typer.Exit()
         if ctx.invoked_subcommand is None:
             typer.echo(ctx.get_help())
             raise typer.Exit()


@app.command("init-nebula")
def init_nebula_command(storage_host: str = typer.Option("storaged", "--storage-host"), storage_port: int = typer.Option(9779, "--storage-port"), env_file: Optional[Path] = EnvFile, nebula_host: Optional[str] = NebulaHost, nebula_port: Optional[int] = NebulaPort, nebula_user: Optional[str] = NebulaUser, nebula_password: Optional[str] = NebulaPass, space: Optional[str] = NebulaSpace, verbose: bool = Verbose) -> None:
    from .initialize_nebula import initialize_nebula
    config = nebula_config(env_file, nebula_host, nebula_port, nebula_user, nebula_password, space or "default")
    try:
        initialize_nebula(config, storage_host, storage_port)
    except RuntimeError as e:
        typer.secho(f"Nebula initialization failed: {e}", fg=typer.colors.RED,err=True)
        raise typer.Exit(code=1) from e
    typer.secho("Nebula cluster is ready", fg=typer.colors.GREEN)

@app.command("apply-schema")
def apply_schema_command(column_schema: Optional[Path] = typer.Option( None, "--column-schema", exists=True, dir_okay=False, help="Column schema YAML describing your data. The graph schema is generated from it.") ,
    ngql_file: Optional[Path] = typer.Option(None, "--ngql-file", exists=True, dir_okay=False, help="Apply a hand-written nGQL script instead of generating one."),
    drop_existing: bool = typer.Option(False, "--drop-existing", help="DROP the target space before creating it. Destroys all graph data in it."),
    wait_seconds: int = typer.Option(10, "--space-create-wait-seconds"), env_file: Optional[Path] = EnvFile,
    nebula_host: Optional[str] = NebulaHost, nebula_port: Optional[int] = NebulaPort, nebula_user: Optional[str] = NebulaUser,
    nebula_password: Optional[str] = NebulaPass, space: Optional[str] = NebulaSpace, verbose: bool = Verbose) -> None:
    from .apply_schema import apply_schema
    if (column_schema is None) == (ngql_file is None):
        raise typer.BadParameter("Pass exactly one of --column-schema or --ngql-file")
    config = nebula_config(env_file, nebula_host, nebula_port, nebula_user, nebula_password, space)
    schema_cols = load_schema_exit(column_schema) if column_schema else None
    if drop_existing:
        typer.confirm(f"This will drop the Nebula space {config.space!r} and all data inside it. Continue?", abort=True)
    count = apply_schema(config, schema_cols, ngql_file, drop_existing, space_create_wait_seconds=wait_seconds)
    typer.secho(f"Applied {count} schema statements to {config.space}", fg=typer.colors.GREEN)

@app.command("load-csv")
def load_csv_command(csv_path: Path = typer.Option(..., "--csv", exists=True, dir_okay=False, help="CSV to load."),
    table: str = typer.Option(..., "--table", help="Destination table name."),
    schema_name: str = typer.Option(..., "--schema-name", help="Destination Postgres schema."),
    primary_key: str = typer.Option(..., "--primary-key", help="Primary key column in the CSV."),
    column_types: Optional[Path] = typer.Option(None, "--column-types", exists=True, dir_okay=False, help="JSON mapping of column name to Postgres type. Anything unlisted becomes text."),
    replace: bool = typer.Option(False, "--replace", help="Drop the destination table first if it already exists."),
    env_file: Optional[Path] = EnvFile, db_url: Optional[str] = DbUrl, db_host: Optional[str] = DbHost, db_port: Optional[int] = DbPort, db_name: Optional[str] = DbName, db_user: Optional[str] = DbUser, db_password: Optional[str] = DbPass, verbose: bool = Verbose) -> None:
    from .loadcsv import load_csv_file
    pg_config = postgres_config(env_file, db_url, db_host, db_port, db_name, db_user, db_password)
    types = json.loads(column_types.read_text(encoding="utf-8")) if column_types else None
    try:
        count = load_csv_file(csv_path, schema_name, table, primary_key, pg_config, column_types, replace)
    except ValueError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from e
    typer.secho(f"Loaded {count} rows into {schema_name}.{table}",fg=typer.colors.GREEN)