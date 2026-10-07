"""Shared fixtures. Tests that touch the database use a separate `<db>_test` database in this
project's Docker PostgreSQL (port 5434), recreated empty for every test."""

import json
import threading
import time
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

from app.config import Settings, load_settings
from app.db.repository import Repository
from app.main import create_app
from tests.fakes import FakeEmbedder, scripted_claude


@pytest.fixture(scope="session")
def settings() -> Settings:
    """The developer's real settings from .env (integration and live tests need them)."""
    return load_settings()


@pytest.fixture(scope="session")
def test_database_url(settings) -> str:
    url = settings.database_url.get_secret_value()
    params = conninfo_to_dict(url)
    params["dbname"] = f"{params['dbname']}_test"
    with psycopg.connect(url, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (params["dbname"],)
        ).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(params["dbname"])))
    return make_conninfo(**params)


def _recreate_schema(repo: Repository, dimension: int) -> None:
    with repo.pool.connection() as conn:
        conn.execute("DROP TABLE IF EXISTS chunks, sections, documents")
    repo.init_schema(dimension)


@pytest.fixture
def repo(test_database_url, settings):
    """A repository on an empty test schema."""
    repository = Repository.connect(test_database_url)
    _recreate_schema(repository, settings.embedding_dimension)
    yield repository
    repository.close()


@pytest.fixture
def recreate_schema():
    return _recreate_schema


@pytest.fixture
def make_client(repo, test_database_url, settings):
    """Start the real app on the test database with fake providers; returns a TestClient."""
    clients: list[TestClient] = []

    def _make(embedder=None, llm=None, **overrides) -> TestClient:
        app_settings = settings.model_copy(
            update={"database_url": SecretStr(test_database_url), **overrides}
        )
        app = create_app(
            app_settings, embedder=embedder or FakeEmbedder(), llm=llm or scripted_claude([])
        )
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


def wait_until_processed(client: TestClient, document_id: str, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        document = client.get(f"/api/documents/{document_id}").json()
        if document["status"] in ("ready", "failed"):
            return document
        time.sleep(0.05)
    raise AssertionError(f"document {document_id} still processing after {timeout}s")


def parse_sse(text: str) -> list[dict[str, Any]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if line and not line.startswith(":")]
        if not lines:
            continue
        fields = dict(line.split(": ", 1) for line in lines)
        events.append({"event": fields["event"], **json.loads(fields["data"])})
    return events


@pytest.fixture
def ask():
    """POST a question and parse the Server-Sent Events: (progress events, final event)."""

    def _ask(client: TestClient, question: str) -> tuple[list[dict], dict]:
        response = client.post("/api/ask", json={"question": question})
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(response.text)
        return events[:-1], events[-1]

    return _ask


@pytest.fixture
def upload():
    """Upload a file and wait for processing to finish; returns the final document."""

    def _upload(client: TestClient, filename: str, data: bytes, timeout: float = 10) -> dict:
        response = client.post("/api/documents", files={"file": (filename, data)})
        assert response.status_code == 202, response.text
        return wait_until_processed(client, response.json()["id"], timeout)

    return _upload


@pytest.fixture
def collect():
    """An `emit` callback that collects events, plus a cancel flag, for service-level tests."""
    events: list[dict[str, Any]] = []
    return events, events.append, threading.Event()
