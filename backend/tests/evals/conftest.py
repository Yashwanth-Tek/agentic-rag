"""Live evaluation fixtures: the real app (Ollama embeddings, real Claude) on the test database,
loaded once per module with the project's sample documents."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.db.repository import Repository
from app.ingestion.validation import SUPPORTED_EXTENSIONS
from app.main import create_app
from tests.conftest import parse_sse, wait_until_processed

SAMPLES = Path(__file__).resolve().parents[3] / "sample-documents"


@pytest.fixture(scope="module")
def live_client(settings, test_database_url):
    """The real stack with every sample document indexed. Needs Ollama, Postgres and the API key."""
    missing = [
        name
        for name in ("lakeside-quality-targets-2026.pdf", "lakeside-benefits-summary-2026.docx")
        if not (SAMPLES / name).exists()
    ]
    if missing:
        pytest.skip(f"run sample-documents/generate.py first (missing {', '.join(missing)})")
    repository = Repository.connect(test_database_url)
    with repository.pool.connection() as conn:
        conn.execute("DROP TABLE IF EXISTS chunks, sections, documents")
    repository.init_schema(settings.embedding_dimension)
    repository.close()

    app = create_app(settings.model_copy(update={"database_url": SecretStr(test_database_url)}))
    with TestClient(app) as client:
        for path in sorted(SAMPLES.iterdir()):
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            response = client.post("/api/documents", files={"file": (path.name, path.read_bytes())})
            assert response.status_code == 202, response.text
            document = wait_until_processed(client, response.json()["id"], timeout=180)
            assert document["status"] == "ready", document
        yield client


@pytest.fixture
def ask_live(live_client):
    def _ask(question: str) -> dict:
        response = live_client.post("/api/ask", json={"question": question})
        assert response.status_code == 200, response.text
        events = parse_sse(response.text)
        final = events[-1]
        assert final["event"] == "result", final
        final["activity"] = [e for e in events if e["event"] == "activity"]
        return final

    return _ask
