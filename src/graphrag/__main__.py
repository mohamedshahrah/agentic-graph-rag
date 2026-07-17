"""Command-line interface.  `graphrag --help`"""

from __future__ import annotations

import typer

app = typer.Typer(add_completion=False, help="Agentic Graph RAG command line.")


@app.command()
def init() -> None:
    """Create Neo4j constraints and indexes."""
    from graphrag.container import Container

    Container().setup_storage()
    typer.echo("Storage initialized.")


@app.command()
def ingest(path: str, user: str = typer.Option("default", help="user namespace")) -> None:
    """Ingest a file or folder into a user's knowledge base."""
    from graphrag.container import Container
    from graphrag.pipelines import IngestPipeline

    stats = IngestPipeline(Container()).run(path, user_id=user)
    typer.echo(
        f"Done. documents={stats.documents} chunks={stats.chunks} "
        f"entities={stats.entities} relations={stats.relations}"
    )


@app.command()
def query(
    question: str,
    style: str = typer.Option("detailed", help="concise | detailed | technical | eli5"),
    user: str = typer.Option("default", help="user namespace"),
) -> None:
    """Ask a question from the terminal."""
    from graphrag.container import Container
    from graphrag.pipelines import QueryService

    result = QueryService(Container()).answer(question, style=style, user_id=user)
    typer.echo("\n" + result.answer + "\n")
    if result.sources:
        typer.echo("Sources:")
        for s in result.sources:
            typer.echo(f"  - {s.source}")


@app.command()
def search(
    query: str, k: int = 8, user: str = typer.Option("default", help="user namespace")
) -> None:
    """Show raw retrieval results (no LLM)."""
    from graphrag.container import Container
    from graphrag.pipelines import QueryService

    for i, chunk in enumerate(QueryService(Container()).search(query, k, user_id=user), 1):
        typer.echo(f"{i}. [{chunk.retriever} {chunk.score:.3f}] {chunk.source}")
        typer.echo(f"   {chunk.text[:160]}...")


@app.command()
def apikey(user: str) -> None:
    """Mint an API key for a user (prints it once)."""
    from graphrag.auth import KeyStore
    from graphrag.container import Container

    container = Container()
    key = KeyStore(container.redis).create_key(user)
    container.tenant(user)  # ensure the user's namespace exists
    typer.echo(key)


@app.command()
def revoke(user: str) -> None:
    """Revoke every API key a user holds (their data stays)."""
    from graphrag.auth import KeyStore
    from graphrag.container import Container

    count = KeyStore(Container().redis).revoke_user(user)
    typer.echo(f"Revoked {count} key(s) for '{user}'.")


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """Start the API server."""
    import uvicorn

    uvicorn.run("graphrag.api.app:create_app", factory=True, host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
