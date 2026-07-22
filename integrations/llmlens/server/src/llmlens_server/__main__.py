"""Command line: `llmlens-server --help`"""

from __future__ import annotations

import re
import secrets as pysecrets

import typer

app = typer.Typer(add_completion=False, help="llmlens observability server.")


@app.command()
def init() -> None:
    """Create ClickHouse + Postgres schemas and seed pricing."""
    from llmlens_server.config import load_settings
    from llmlens_server.storage import setup_storage

    settings, secrets = load_settings()
    setup_storage(settings, secrets)
    typer.echo("Storage initialized.")


@app.command()
def create_project(name: str) -> None:
    """Create a project and mint a secret ingest key (printed once)."""
    from llmlens_server.config import load_settings
    from llmlens_server.core.keys import generate_key, hash_key
    from llmlens_server.storage import postgres
    from llmlens_server.storage.postgres import repos

    _, secrets = load_settings()
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "project"
    project_id = f"{slug}-{pysecrets.token_hex(3)}"
    key = generate_key("sk")
    with postgres.connect(secrets.postgres_dsn) as conn:
        repos.create_project(conn, project_id, name)
        repos.add_api_key(conn, project_id, hash_key(key), "secret")
    typer.echo(f"project_id: {project_id}")
    typer.echo(f"secret_key: {key}")


@app.command()
def worker() -> None:
    """Run the ingest + alert worker."""
    from llmlens_server.worker import run

    run()


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Start the API server."""
    import uvicorn

    uvicorn.run(
        "llmlens_server.api.app:create_app",
        factory=True, host=host, port=port, reload=reload,
    )


if __name__ == "__main__":
    app()
